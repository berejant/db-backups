#!/usr/bin/env python3
from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import os
import time
import subprocess
from urllib.parse import parse_qs
import shutil

BACKUP_DIR = '/backup'
DATA_DIR = '/var/lib/mysql'
Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)


def print_backups_list():
    output = '<ul>'
    for dirname in os.listdir(BACKUP_DIR):
        if not os.path.isdir(BACKUP_DIR + '/' + dirname):
            continue
        output += '<li>'
        output += '<button formaction="/create_incremental_backup" type="submit" name="backup_name" value="%s">' \
                  'Create Incremental backup' \
                  '</button>&nbsp;' % dirname
        output += '<button formaction="/restore_backup" type="submit" name="backup_name" value="%s">' \
                  'Restore backup' \
                  '</button>&nbsp;' % dirname
        output += '<button formaction="/delete_backup" type="submit" name="backup_name" value="%s">' \
                  'Delete backup' \
                  '</button>&nbsp;' % dirname
        output += '<span>%s</span>&nbsp;' % dirname
        output += '</li>'
    output += '</ul>'

    return output


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(
            '<!DOCTYPE html>'
            '<html><head><title>Backup Management</title></head>'
            '<body><form method="POST">'
            '<p><button formaction="/create_full_backup" type="submit" name="backup_name" value="new">'
            'Create Full backup'
            '</button>'
            '</p>'.encode("UTF-8")
        )
        self.wfile.write(print_backups_list().encode("UTF-8"))
        self.wfile.write('</form></body></html>'.encode("UTF-8"))

    def do_delete(self, backup_name):
        shutil.rmtree(os.path.join(BACKUP_DIR, backup_name))

    def do_restore(self, backup_name):
        incremental_dirs = backup_name.split("_based_on_")
        backup_dir = incremental_dirs.pop()
        source_base = os.path.join(BACKUP_DIR, backup_dir)
        print(source_base + "\n")

        tmp_backup_dir = os.path.join("/tmp", backup_dir)
        shutil.rmtree(tmp_backup_dir, ignore_errors=True)
        shutil.copytree(source_base, tmp_backup_dir)

        subprocess.run([
            "xtrabackup", "--prepare", "--apply-log-only", "--target-dir=" + tmp_backup_dir,
        ], check=True)

        incremental_dir = backup_dir
        while incremental_dirs:
            incremental_dir = incremental_dirs.pop() + "_based_on_" + incremental_dir
            tmp_incremental_dir = os.path.join("/tmp", incremental_dir)
            shutil.rmtree(tmp_incremental_dir, ignore_errors=True)
            shutil.copytree(os.path.join(BACKUP_DIR, incremental_dir), tmp_incremental_dir)
            subprocess.run([
                "xtrabackup", "--prepare",  "--apply-log-only",
                "--target-dir=" + tmp_backup_dir,
                "--incremental-dir=" + tmp_incremental_dir
            ], check=True)
            shutil.rmtree(tmp_incremental_dir, ignore_errors=True)

        subprocess.run(["docker", "stop", "percona"], check=True)
        for filename in os.listdir(DATA_DIR):
            file_path = os.path.join(DATA_DIR, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print('Failed to delete %s. Reason: %s' % (file_path, e))

        subprocess.run([
            "xtrabackup", "--copy-back", "--datadir=" + DATA_DIR, "--target-dir=" + tmp_backup_dir
        ], check=True)
        shutil.rmtree(tmp_backup_dir, ignore_errors=True)

        subprocess.run(['chown', '-R', '1001:1001', DATA_DIR], check=True)
        subprocess.run(["docker", "start", "percona"], check=True)

    def do_backup(self, new_backup_name, incremental_base_name=None):
        xtrabackup_command = [
            "xtrabackup",
            "--host=percona",
            "--user=root",
            "--password=" + os.environ['MYSQL_ROOT_PASSWORD'],
            "--backup",
            "--datadir=" + DATA_DIR,
            "--target-dir=" + os.path.join(BACKUP_DIR, new_backup_name),
            "--lock-ddl-timeout=10",
            "--ftwrl-wait-timeout=10",
        ]
        if incremental_base_name:
            xtrabackup_command.append('--incremental-basedir=' + os.path.join(BACKUP_DIR, incremental_base_name))

        subprocess.run(xtrabackup_command, check=True)

    def do_POST(self):
        new_backup_name = time.strftime("%Y-%m-%d_%H-%M-%S")

        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        print(post_data + "\n")
        post_data = parse_qs(post_data)
        if "backup_name" not in post_data:
            self.send_response(400)
            self.end_headers()
            return
        backup_name = post_data["backup_name"][0]

        try:
            self.send_response(303)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Content-Length', '0')
            self.send_header('Location', '/')
            self.end_headers()

            if self.path == '/delete_backup':
                self.do_delete(backup_name)
            elif self.path == '/restore_backup':
                self.do_restore(backup_name)

            elif self.path == '/create_incremental_backup':
                new_backup_name += "_based_on_" + backup_name
                self.do_backup(new_backup_name, backup_name)
            elif self.path == '/create_full_backup':
                new_backup_name += "_full"
                self.do_backup(new_backup_name)
            else:
                self.send_response(400)
                self.end_headers()
                return

        except subprocess.TimeoutExpired as ex:
            print(ex.cmd + " timeout expired \n")
            self.send_response(500)
            self.end_headers()

        except subprocess.CalledProcessError as ex:
            print(ex.cmd)
            print(ex.output)
            print(ex.stderr)
            self.send_response(500)
            self.end_headers()

    # Health check
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


print("Hello!\n")
httpd = HTTPServer(('0.0.0.0', 80), SimpleHTTPRequestHandler)
httpd.serve_forever()
