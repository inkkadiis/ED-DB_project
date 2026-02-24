import streamlit as st
import pandas as pd
import re
import os
from dotenv import load_dotenv
import streamlit.components.v1 as components
import urllib.parse #

# .env 파일 로드
load_dotenv()
KAKAO_JS_KEY = os.getenv("KAKAO_JS_KEY")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

# ==========================================
# [수정 포인트 1] 필터링 및 정제 규칙 설정
# ==========================================
MIN_EMPLOYEES = 15       # 최소 인원
MAX_EMPLOYEES = 300      # 최대 인원
INDUSTRY_MIN = 10        # 산업코드 시작
INDUSTRY_MAX = 34        # 산업코드 끝
APPEND_NAME = True       # 주소 뒤에 공장명 붙일지 여부 (실용주의 모드)
# ==========================================

st.set_page_config(layout="wide", page_title="공장 DB 검수기")

# 디버깅용: 인식된 키 확인 (확인 후 삭제 가능)
st.write(f"현재 인식된 키: {KAKAO_JS_KEY}")

# --- [로그인 기능] ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    pwd = st.text_input("접속 비밀번호를 입력하세요", type="password")
    if pwd == ACCESS_PASSWORD:
        st.session_state.auth = True
        st.rerun()
    else:
        st.stop()

# --- [데이터 처리 엔진] ---
@st.cache_data
def load_and_filter(file):
    # 파일 확장자 확인 (엑셀 vs CSV)
    if file.name.endswith('.xlsx'):
        df = pd.read_excel(file, header=1)
    else:
        df = pd.read_csv(file, header=1)
    
    # 1. 종업원수 및 기업구분 필터링
    df['종업원수'] = pd.to_numeric(df['종업원수'], errors='coerce')
    df = df[(df['종업원수'] >= MIN_EMPLOYEES) & (df['종업원수'] <= MAX_EMPLOYEES)]
    df = df[df['기업구분'].str.contains('소기업|중기업', na=False)]
    
    # 2. 산업코드 필터링
    def check_ind(code):
        if pd.isna(code): return False
        c = str(code).split(',')[0].strip()[:2]
        return c.isdigit() and INDUSTRY_MIN <= int(c) <= INDUSTRY_MAX
    
    df = df[df['업종코드'].apply(check_ind)]
    
    # 3. 주소 정제 함수 (중첩 괄호 완벽 제거)
    def clean_addr(row):
        addr = str(row['주소'])
        name = str(row['공장명'])
        
        clean_a = addr
        
        # 1. 괄호가 더 이상 없을 때까지 안쪽 괄호부터 계속 지우기 (양파 껍질 로직)
        while re.search(r'\([^()]*\)', clean_a):
            clean_a = re.sub(r'\([^()]*\)', '', clean_a)
            
        # 2. 혹시라도 짝이 안 맞아 남은 찌꺼기 괄호 기호 강제 삭제
        clean_a = clean_a.replace('(', '').replace(')', '')
        
        # 3. '외 n필지' 등 불필요한 문구 삭제
        clean_a = re.sub(r'외\s?\d?필지.*', '', clean_a)
        clean_a = re.sub(r'외\s?\d?.*', '', clean_a) # '외 1' 처럼 적힌 경우도 대비
        
        # 4. 양옆 지저분한 쉼표나 다중 띄어쓰기 정리
        clean_a = re.sub(r'\s+', ' ', clean_a).strip().rstrip(',')
        
        # 실용주의 모드 적용 (공장명 결합)
        final_a = f"{clean_a} {name}" if APPEND_NAME else clean_a
        return pd.Series([clean_a, final_a])

    # 주소 정제 적용
    df[['검색용주소', '최종주소']] = df.apply(clean_addr, axis=1)
    
    # 검색용 주소 기준 중복 제거
    df = df.drop_duplicates(subset=['검색용주소'])
    df['검수결과'] = "미검수"
    return df.reset_index(drop=True)

# --- [UI 레이아웃] ---
st.title("🏭 울산 공장 DB 검수 시스템")

uploaded_file = st.file_uploader("울산 DB 엑셀 파일을 업로드하세요 (CSV 또는 XLSX)", type=['csv', 'xlsx'])

if uploaded_file:
    # 새로운 파일이 업로드되면 데이터를 새로고침하도록 로직 추가
    if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
        st.session_state.df = load_and_filter(uploaded_file)
        st.session_state.current_file = uploaded_file.name
    
    df = st.session_state.df
    
    # 상단 대시보드
    col1, col2, col3 = st.columns(3)
    total = len(df)
    done = len(df[df['검수결과'] != "미검수"])
    pass_cnt = len(df[df['검수결과'] == "PASS"])
    
    col1.metric("전체 타겟", f"{total}건")
    col2.metric("검수 진행", f"{done}건 ({int(done/total*100) if total > 0 else 0}%)")
    col3.metric("최종 PASS", f"{pass_cnt}건")

    st.divider()

    # 메인 작업창
    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.subheader("검수 리스트")
        pending_df = df[df['검수결과'] == "미검수"]
        if not pending_df.empty:
            target_idx = pending_df.index[0]
            target_row = df.iloc[target_idx]
            
            st.info(f"현재 검수 중: **{target_row['공장명']}**")
            st.write(f"📍 {target_row['최종주소']}")
            
            c1, c2 = st.columns(2)
            if c1.button("✅ PASS (가동중)", use_container_width=True):
                st.session_state.df.at[target_idx, '검수결과'] = "PASS"
                st.rerun()
            if c2.button("❌ 폐업/철거/이전", use_container_width=True):
                st.session_state.df.at[target_idx, '검수결과'] = "폐업"
                st.rerun()
        else:
            st.success("🎉 모든 검수가 완료되었습니다!")

    with right_col:
        if not pending_df.empty:
            search_addr = target_row['검색용주소']
            
            # Flask 서버(localhost:5001)를 통해 지도 로드 - 올바른 origin 제공
            encoded_addr = urllib.parse.quote(search_addr)
            map_url = f"http://localhost:5001/map?addr={encoded_addr}"
            
            # iframe으로 Flask 서버의 맵 페이지 로드
            components.iframe(map_url, height=550, scrolling=False)

    # --- [다운로드 섹션] ---
    st.divider()
    d_col1, d_col2 = st.columns(2)
    
    master_csv = df.to_csv(index=False).encode('utf-8-sig')
    d_col1.download_button("📂 전체 검수 마스터 다운로드", master_csv, "ulsan_master.csv", "text/csv")
    
    post_df = df[df['검수결과'] == "PASS"][['최종주소']]
    post_df.insert(0, '우편번호', '12345') # 임시 우편번호
    post_csv = post_df.to_csv(index=False, header=False).encode('utf-8-sig')
    d_col2.download_button("📮 우체국 업로드용 다운로드", post_csv, "post_upload.csv", "text/csv")