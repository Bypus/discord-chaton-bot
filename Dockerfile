# syntax = docker/dockerfile:1

FROM python:3.12

WORKDIR /discord-nhlib-bot
COPY requirements.txt /discord-nhlib-bot
RUN pip install -r requirements.txt
COPY . /discord-nhlib-bot

CMD python bot.py