FROM python:3.12-alpine

WORKDIR /srv
COPY server.py sync.js index.html ./

ENV PORT=80 DATA_DIR=/data
EXPOSE 80

CMD ["python", "server.py"]
