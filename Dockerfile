FROM python:3.12-alpine

WORKDIR /srv
COPY server.py sync.js index.html ./

ENV PORT=8000 DATA_DIR=/data
EXPOSE 8000

CMD ["python", "server.py"]
