FROM python:3.12-slim

WORKDIR /stub
COPY tests/system/model_services_stub/server.py /stub/server.py

EXPOSE 8090
CMD ["python", "/stub/server.py"]
