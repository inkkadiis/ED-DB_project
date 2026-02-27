# Kakao Maps API 도메인 등록 가이드

## 문제 해결 방법

"domain mismatched! caller=about://" 오류는 Streamlit의 `components.html()`이 `srcdoc` 속성을 사용하여 iframe의 origin이 `about://`로 표시되어 발생합니다. 이를 해결하기 위해 **별도의 Flask 서버**를 통해 지도를 제공합니다.

## 필수 등록 도메인

Kakao Developers 콘솔 (https://developers.kakao.com)에서 다음 도메인을 등록해야 합니다:

### 로컬 개발 환경

- `http://localhost:5001` **중요: Flask 서버가 지도를 제공하는 포트입니다!**

### 등록 방법

1. **Kakao Developers 접속**
   - https://developers.kakao.com 로그인

2. **애플리케이션 선택**
   - 내 애플리케이션 → 사용 중인 앱 선택

3. **플랫폼 설정**
   - 좌측 메뉴에서 "플랫폼" 클릭
   - "Web 플랫폼 등록" 클릭 (이미 등록되어 있다면 수정)

4. **도메인 변경/추가**
   - **기존**: `http://localhost:8502` 삭제 (더 이상 필요 없음)
   - **새로 등록**: `http://localhost:5001` 입력
   - 저장

## 시스템 아키텍처

```
브라우저
  ↓
Streamlit 앱 (localhost:8502)
  ↓
components.iframe()
  ↓
Flask 서버 (localhost:5001) ← Kakao가 이 도메인을 검증
  ↓
Kakao Maps API
```

## 앱 실행 방법

**중요**: 이제 두 개의 서버를 동시에 실행해야 합니다!

### 방법 1: 수동 실행

**터미널 1 - Flask 맵 서버 실행:**

```bash
python map_server.py
```

**터미널 2 - Streamlit 앱 실행:**

```bash
streamlit run app.py
```

### 방법 2: start.bat 사용 (권장)

```bash
start.bat
```

## 변경 사항 요약

### 문제의 원인

- Streamlit의 `components.html()`은 `srcdoc` 속성 사용
- iframe의 origin이 `about://`로 표시됨
- Kakao API가 등록된 도메인과 매칭 불가

### 해결 방법

- Flask 서버를 별도로 실행하여 지도 HTML 제공
- `components.iframe()`으로 Flask 서버의 URL 로드
- iframe의 origin이 `http://localhost:5001`로 정상 표시
- Kakao API가 등록된 도메인과 매칭 성공

## 문제가 계속되는 경우

1. **Flask 서버가 실행 중인지 확인**
   - `http://localhost:5001/map?addr=서울특별시` 브라우저에서 직접 접속 테스트

2. **Kakao 도메인 등록 확인**
   - Kakao Developers 콘솔에서 정확히 `http://localhost:5001` 등록 확인
   - 오타, 공백, 슬래시 등 확인

3. **로그 확인**
   - Flask 서버 터미널에서 요청 로그 확인
   - 브라우저 F12 콘솔에서 에러 메시지 확인

4. **방화벽 설정**
   - Windows 방화벽이 포트 5001을 차단하는지 확인
