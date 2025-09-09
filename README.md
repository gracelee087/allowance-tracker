# 💶 Allowance Tracker

음성 인식으로 지출을 기록하고 Google Sheets에 실시간 동기화하는 앱입니다.

## 🚀 Features

- **🎤 실시간 음성 입력**: 마이크로 바로 말해서 지출 기록
- **📊 Google Sheets 연동**: 실시간으로 스프레드시트에 저장
- **💰 예산 관리**: 월 예산 설정 및 사용량 추적
- **🧠 LLM 파싱**: OpenAI를 통한 지능형 텍스트 파싱 (선택사항)
- **📱 모바일 지원**: 안드로이드 브라우저에서 사용 가능

## 📝 입력 형식

```
날짜 / 장소 / 금액 / 메모
```

### 예시:
- `today / supermarket / 35 euro / lunch`
- `yesterday / cafe / 5 euro / morning coffee`
- `this month / gas station / 45 euro / fuel`
- `i don't know / mart / 10 euro / snacks`

### 지원하는 날짜 표현:
- `today`, `yesterday`
- `this month`, `last month`
- `i don't know` (오늘 날짜로 설정)
- 한국어: `오늘`, `어제`, `이번 달`, `지난 달`, `모르겠어`

## 🛠️ 설치 및 실행

### 1. 저장소 클론
```bash
git clone <your-repo-url>
cd kpoket
```

### 2. 가상환경 생성 및 활성화
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

### 3. 의존성 설치
```bash
pip install -r requirements.txt
```

### 4. 환경변수 설정
`env_template.txt`를 `.env`로 복사하고 설정:
```bash
cp env_template.txt .env
```

`.env` 파일에서 다음 값들을 설정:
- `GOOGLE_SHEETS_URL`: Google Sheets URL
- `OPENAI_API_KEY`: OpenAI API 키 (선택사항)

### 5. Google Sheets 설정
1. Google Cloud Console에서 Service Account 생성
2. Google Sheets API 활성화
3. Service Account JSON 키 다운로드
4. Google Sheets를 Service Account 이메일로 공유 (편집자 권한)

### 6. 앱 실행
```bash
streamlit run app.py
```

## ☁️ 클라우드 배포

### Streamlit Community Cloud
1. GitHub에 코드 푸시
2. [Streamlit Community Cloud](https://share.streamlit.io)에서 배포
3. 환경변수를 Streamlit 대시보드에서 설정

## 📱 모바일 사용

안드로이드 브라우저에서:
1. 배포된 Streamlit 앱 URL 접속
2. 마이크 권한 허용
3. 음성으로 지출 기록

## 🔧 설정

### Whisper 모델 설정
환경변수로 Whisper 모델 크기 조정:
- `WHISPER_MODEL=tiny` (빠름, 낮은 정확도)
- `WHISPER_MODEL=small` (기본값)
- `WHISPER_MODEL=medium` (높은 정확도)
- `WHISPER_MODEL=large-v3` (최고 정확도)

### LLM 파싱 (선택사항)
- OpenAI API 키 설정 시 LLM 기반 파싱 사용 가능
- 더 유연한 음성 인식 결과 처리

## 📊 데이터 구조

### Excel/Google Sheets 컬럼:
- `when`: 날짜 (YYYY-MM-DD)
- `where`: 장소
- `amount`: 금액 (EUR)
- `memo`: 메모

## 🛡️ 보안

- 민감한 정보는 환경변수로 관리
- `.gitignore`에 credentials 파일 제외
- Google Sheets는 Service Account로 안전하게 접근

## 📄 라이선스

MIT License
