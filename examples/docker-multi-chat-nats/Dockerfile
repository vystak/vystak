FROM python:3.12-slim
WORKDIR /app

COPY _vystak/requirements.txt /app/_vystak/requirements.txt
RUN pip install -r /app/_vystak/requirements.txt

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
CMD ["python", "server.py"]
