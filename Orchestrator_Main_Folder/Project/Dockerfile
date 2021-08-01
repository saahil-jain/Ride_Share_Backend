FROM python:3

ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1

RUN apt-get update && apt-get install -y --no-install-recommends apt-utils
RUN apt-get upgrade -y

RUN mkdir /app
WORKDIR /app

COPY . /app

RUN pip3 install --no-cache-dir -r requirements.txt