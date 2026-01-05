FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# LibreOffice Calc + Python + UNO 바인딩 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    libreoffice-calc \
    python3-uno \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# FastAPI 등 파이썬 의존성
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# 프로젝트 코드 복사
COPY . /app

# UNO 환경 변수 (libreoffice 내부 설정 파일 위치)
ENV URE_BOOTSTRAP=vnd.sun.star.pathname:/usr/lib/libreoffice/program/fundamentalrc

# FastAPI 실행
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
