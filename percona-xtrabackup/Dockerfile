FROM percona/percona-xtrabackup:8.0

# Install Docker from Docker Inc. repositories.
RUN curl -sSL https://get.docker.com/ | sh
RUN yum update -y && yum install -y python3 python3-requests && yum clean all

COPY xtrabackup-api.py /xtrabackup-api.py

EXPOSE 80
ENTRYPOINT ["/xtrabackup-api.py"]
HEALTHCHECK CMD curl -I --fail http://localhost:80 || exit 1

