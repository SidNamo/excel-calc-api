# Excel API (FastAPI + LibreOffice UNO)

LibreOffice(헤드리스) 기반으로 엑셀 파일(A/S 템플릿)을 로드한 뒤, 요청 payload를 입력값으로 주고 계산 결과를 반환하는 **계산 전용 API** 프로젝트입니다.  
워커(LibreOffice 프로세스) 세트를 여러 개 띄워 동시 요청을 처리하고, S3의 최신 A/S 파일로 워커를 재시작(리로드)할 수 있도록 구성되어 있습니다.

---

## 핵심 기능

- **/calc**: 계산 요청(입력 데이터/출력 셀 목록) → 결과 반환
- **작업 큐 기반 처리**: 요청을 큐에 적재하고 워커가 순차 처리
- **멀티 워커 세트(SET_COUNT)**: 워커 세트를 여러 개 띄워 동시성 확보
- **S3 기반 최신 A/S 파일 동기화**
- **관리자 리로드(/admin/reload)**: S3의 최신 파일 기준으로 워커를 순차 재시작

---

## 프로젝트 구조(요약)

- `main.py` : FastAPI 앱 엔트리, 워커 초기화/리로드 트리거
- `router.py` : API 라우팅(`/calc`, `/admin/reload`)
- `task_queue.py` : 요청 큐/워커 스케줄링 로직
- `libreoffice.py` : LibreOffice(UNO) 워커 실행/제어, S3 다운로드/최신 키 조회
- `docker-compose.yml`, `Dockerfile` : 컨테이너 실행 환경

---

## 실행 방법 (Docker Compose)

```bash
docker compose up --build
```

기본 포트 매핑:
- Host `80` → Container `8080`

> 로컬에서 80 포트가 부담되면 `docker-compose.yml`의 `"80:8080"`을 `"8080:8080"` 등으로 변경하세요.

---

## 환경 변수

`docker-compose.yml` 기준으로 아래 env를 사용합니다.

- `SET_COUNT` : 워커 세트 수 (예: 2)
- `LOG_LEVEL` : `INFO` / `DEBUG`
- `AWS_S3_BUCKET_NAME` : S3 버킷 이름
- `AWS_S3_ACCESS_KEY` : S3 접근 키
- `AWS_S3_SECRET_KEY` : S3 시크릿 키
- `AWS_REGION` : 리전 (예: `ap-northeast-2`)
- `S3_PREFIX_A` : A 파일 prefix (예: `Contents/Excel/A/`)
- `S3_PREFIX_S` : S 파일 prefix (예: `Contents/Excel/S/`)

⚠️ **주의**: 실제 키는 절대 Git에 커밋하지 말고, 로컬 `.env` 또는 배포 환경 Secret(예: Docker secret, K8s Secret)로 주입하세요.

---

## API

### 1) POST `/calc`

엑셀 계산 요청을 처리합니다.

요청 바디는 대략 아래 형태를 가집니다(프로젝트의 Pydantic 모델에 맞춰 조정).

```json
{
  "A": {
    "input": [{"key": "VALUE1", "value": 10}],
    "output": ["Sheet1!B2", "Sheet1!C5"]
  },
  "S": {
    "input": [{"key": "VALUE2", "value": 3}],
    "output": ["Sheet1!D7"]
  }
}
```

응답은 워커에서 계산된 결과를 반환합니다(구체 스키마는 현재 코드/템플릿 구성에 따라 달라질 수 있습니다).

---

### 2) POST `/admin/reload`

S3 최신 A/S 파일을 기준으로 워커를 순차 재시작합니다.

```bash
curl -X POST http://localhost:80/admin/reload -H "Content-Type: application/json" -d "{}"
```