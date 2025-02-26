# syntax = docker/dockerfile:1

FROM python:3.12

WORKDIR /discord-chaton-bot
COPY requirements.txt /discord-chaton-bot
RUN pip install -r requirements.txt
COPY . /discord-chaton-bot

CMD python bot.py