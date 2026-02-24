import streamlit as st
import pandas as pd
import re
import os
import io
from dotenv import load_dotenv
import streamlit.components.v1 as components
import urllib.parse

# .env 파일 로드
load_dotenv()
KAKAO_JS_KEY = os.getenv("KAKAO_JS_KEY")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

# ==========================================
# [설정] 필터링 및 정제 규칙
# ==========================================
MIN_EMPLOYEES = 15       # 최소 인원
MAX_EMPLOYEES = 300      # 최대 인원
INDUSTRY_MIN = 10        # 산업코드 시작
INDUSTRY_MAX = 34        # 산업코드 끝
APPEND_NAME = True       # 주소 뒤에 공장명 붙일지 여부
# ==========================================

st.set_page_config(layout="wide", page_title="전국 공장 DB 검수기")

# 기존 코드
st.set_page_config(layout="wide", page_title="전국 공장 DB 검수기")

# [디자인 커스텀 영역] CSS 주입
st.markdown("""
<style>
    /* 1. 상단 오른쪽 스트림릿 기본 햄버거 메뉴 숨기기 (깔끔한 사내 툴처럼 보이게) */
    #MainMenu {visibility: hidden;}
    
    /* 2. 맨 아래 'Made with Streamlit' 워터마크 숨기기 */
    footer {visibility: hidden;}
    
    /* 3. 상단 여백(Padding) 확 줄여서 지도를 더 넓게 쓰기 */
    .block-container {
        padding-top: 2.7rem;
        padding-bottom: 2.7rem;
    }
    
    /* 4. 버튼(PASS/폐업) 디자인 바꾸기 (기본 버튼을 예쁘게) */
    .stButton > button {
        border-radius: 8px; /* 모서리 둥글게 */
        font-weight: bold;  /* 글씨 굵게 */
        transition: 0.3s;   /* 마우스 올렸을 때 애니메이션 */
    }
    
    /* 5. 버튼에 마우스 올렸을 때 테두리 색상 변경 */
    .stButton > button:hover {
        border-color: #FF4B4B; 
        color: #FF4B4B;
    }
            
    hr {
        margin-top: 1em !important;
        margin-bottom: 1em !important;
    }
            
    [data-testid="column"] [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
    }

    
   
</style>
""", unsafe_allow_html=True)

# --- [로그인 기능] ---
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    # 2. 화면을 5:5로 쪼개서 50% 너비만 차지하게 만듭니다.
    # (만약 가운데 정렬하고 싶다면 st.columns([1, 2, 1]) 하고 with c2: 에 넣으시면 됩니다)
    login_col1, login_col2 = st.columns([1, 1])
    
    with login_col1:
        st.info("비밀번호를 입력해 주세요.")
        pwd = st.text_input("접속 비밀번호", type="password")
        
        # 비밀번호를 입력했을 때만 검사
        if pwd:
            if pwd == ACCESS_PASSWORD:
                st.session_state.auth = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다. 다시 확인해 주세요.")
                
    # 인증 전에는 아래(데이터 로드 등) 로직이 아예 실행되지 않도록 막음
    st.stop()

# --- [데이터 처리 엔진] ---
@st.cache_data
def load_and_filter(file):
    # 1. 파일 포인터를 맨 앞으로 이동 (스트림릿 안전장치)
    file.seek(0)
    
    # 2. 우선 파일의 첫 줄(header=0)을 기준으로 읽어보기
    if file.name.endswith('.xlsx'):
        df = pd.read_excel(file)
    else:
        df = pd.read_csv(file)
        
    # 3. 백업 파일 감지기: '검수결과' 컬럼이 있으면 무조건 백업 파일!
    if '검수결과' in df.columns and '최종주소' in df.columns:
        # 정제/필터링 로직을 모두 건너뛰고 기존 작업 상태 그대로 반환
        return df.reset_index(drop=True)
        
    # 4. 백업 파일이 아니라면 원본 양식! (header=1로 다시 올바르게 읽기)
    file.seek(0) # 파일을 다시 읽기 위해 포인터 되감기
    if file.name.endswith('.xlsx'):
        df = pd.read_excel(file, header=1)
    else:
        df = pd.read_csv(file, header=1)
    
    # 혹시 모를 엑셀 공백 제거
    df.columns = df.columns.str.strip()
    
    # --- 여기서부터는 원본 파일 전용 클리닝 로직 ---
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
    
    # 3. 주소 정제 함수
    def clean_addr(row):
        addr = str(row['주소'])
        name = str(row['공장명'])
        clean_a = addr
        while re.search(r'\([^()]*\)', clean_a):
            clean_a = re.sub(r'\([^()]*\)', '', clean_a)
        clean_a = clean_a.replace('(', '').replace(')', '')
        clean_a = re.sub(r'외\s?\d?필지.*', '', clean_a)
        clean_a = re.sub(r'외\s?\d?.*', '', clean_a)
        clean_a = re.sub(r'\s+', ' ', clean_a).strip().rstrip(',')
        final_a = f"{clean_a} {name}" if APPEND_NAME else clean_a
        return pd.Series([clean_a, final_a])

    df[['검색용주소', '최종주소']] = df.apply(clean_addr, axis=1)
    df = df.drop_duplicates(subset=['검색용주소'])
    df['검수결과'] = "미검수"
    
    return df.reset_index(drop=True)

# --- [UI 레이아웃] ---

spacer_left, center_col, spacer_right = st.columns([1, 2, 1])

with center_col:
    # 제목과 업로드 칸을 모두 이 가운데 기둥(center_col) 안에 넣습니다.
    st.title("전국 공장 DB 검수 시스템")
    uploaded_file = st.file_uploader("공장 DB 파일을 업로드하세요 (CSV 또는 XLSX)", type=['csv', 'xlsx'])

if uploaded_file:
    #  추가된 안전장치: history가 아예 없으면 일단 빈 리스트로 만들어 둠
    if "history" not in st.session_state:
        st.session_state.history = []

    # 새로운 파일이 업로드되면 데이터를 새로고침하도록 로직 추가
    if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
        st.session_state.df = load_and_filter(uploaded_file)
        st.session_state.current_file = uploaded_file.name
        st.session_state.history = [] # 새로운 파일이면 기록 초기화
    
    df = st.session_state.df
    
    
    # 상단 대시보드
    dash_spacer_left, col1, col2, col3, dash_spacer_right = st.columns([1.5, 0.8, 0.8, 0.8, 1.5])
    
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
            st.write(f"{target_row['최종주소']}")
            
            # --- [기존 검수 버튼] ---
            c1, c2 = st.columns(2)
            if c1.button("✅ PASS (가동중)", use_container_width=True):
                st.session_state.history.append(target_idx) # 기록 저장
                st.session_state.df.at[target_idx, '검수결과'] = "PASS"
                st.rerun()
            if c2.button("❌ 폐업/철거/이전", use_container_width=True):
                st.session_state.history.append(target_idx) # 기록 저장
                st.session_state.df.at[target_idx, '검수결과'] = "폐업"
                st.rerun()
                
            st.write("---")
            
            # --- [뒤로 가기 & 중간 저장 버튼] ---
            action_c1, action_c2 = st.columns(2)
            
            # 1. 뒤로 가기 (history가 비어있으면 버튼 비활성화)
            if action_c1.button("⏪ 이전 취소 (Undo)", disabled=len(st.session_state.history)==0, use_container_width=True):
                last_idx = st.session_state.history.pop() # 마지막 작업 꺼내기
                st.session_state.df.at[last_idx, '검수결과'] = "미검수" # 상태 되돌리기
                st.rerun()
                
            # 2. 중간 저장 (현재 상태 그대로 엑셀 다운로드)
            output_backup = io.BytesIO()
            with pd.ExcelWriter(output_backup, engine='openpyxl') as writer:
                st.session_state.df.to_excel(writer, index=False, sheet_name='중간저장')
            backup_data = output_backup.getvalue()

            safe_filename = os.path.splitext(st.session_state.current_file)[0]
            
            action_c2.download_button(
                label="💾 진행상황 중간저장",
                data=backup_data,
                file_name=f"{safe_filename}_backup.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.success("🎉 모든 검수가 완료되었습니다!")

    with right_col:
        if not pending_df.empty:
            search_addr = target_row['검색용주소']
            encoded_addr = urllib.parse.quote(search_addr)
            # GitHub Pages 기반 지도 경로
            map_url = f"https://inkkadiis.github.io/ED-DB_project/static/map.html?addr={encoded_addr}&key={KAKAO_JS_KEY}"
            components.iframe(map_url, height=700, scrolling=False)

   # --- [다운로드 섹션] ---
    st.divider()
    
    
    # 기존 업로드된 파일명에서 확장자(.xlsx, .csv) 제거 후 순수 이름만 추출
    original_filename = os.path.splitext(st.session_state.current_file)[0]
    
    # 버튼과 설명을 담을 3개의 구역(컬럼) 생성
    spacer_left, d_col1, d_col2, d_col3, spacer_right = st.columns([1, 1, 1, 1, 1], gap="large")
    
    # ---------------------------------------------------------
    # 1. 데이터 클리닝이 된 파일
    # ---------------------------------------------------------
    with d_col1:
        st.markdown("#### 📄 1. 데이터 클리닝 원본")
        st.caption("조건(종업원수, 산업코드)에 맞게 필터링되고, 주소 정제(괄호 제거 등)가 완료된 **검수 전 전체 원본 데이터**입니다.")
        
        # 다운로드 전 '검수결과' 컬럼 삭제 (에러 방지를 위해 errors='ignore' 추가)
        df_download_1 = df.drop(columns=['검수결과'], errors='ignore')
        
        output1 = io.BytesIO()
        with pd.ExcelWriter(output1, engine='openpyxl') as writer:
            df_download_1.to_excel(writer, index=False, sheet_name='클리닝완료_전체')
        excel_data1 = output1.getvalue()
        
        st.download_button(
            label="다운로드",
            data=excel_data1,
            file_name=f"{original_filename}_1_cleaned_data_master.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # ---------------------------------------------------------
    # 2. PASS 된 애들만 모여 있는 파일
    # ---------------------------------------------------------
    with d_col2:
        st.markdown("#### ✅ 2. PASS 완료 목록")
        st.caption("직접 검수하여 **'PASS(가동중)'**으로 판정된 공장들만 모아둔 파일입니다. 공장명, 전화번호 등 모든 열이 포함되어 있습니다.")
        
        # PASS 데이터만 필터링한 뒤, '검수결과' 컬럼 삭제
        pass_full_df = df[df['검수결과'] == "PASS"]
        df_download_2 = pass_full_df.drop(columns=['검수결과'], errors='ignore')
        
        output2 = io.BytesIO()
        with pd.ExcelWriter(output2, engine='openpyxl') as writer:
            df_download_2.to_excel(writer, index=False, sheet_name='PASS_완료')
        excel_data2 = output2.getvalue()
        
        st.download_button(
            label="다운로드",
            data=excel_data2,
            file_name=f"{original_filename}_2_pass_completed_list.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # ---------------------------------------------------------
    # 3. 우체국용 주소만 있는 파일
    # ---------------------------------------------------------
    with d_col3:
        st.markdown("#### 📮 3. 우체국 업로드용")
        st.caption("PASS 데이터 중에서 DM 발송을 위해 맨 위 제목 열을 지우고, **'우편번호(빈칸)'와 '최종주소'** 딱 두 개 열만 남긴 파일입니다.")
        
        # 3번 파일은 이미 필요한 컬럼 2개만 뽑아내므로 '검수결과' 삭제가 필요 없음
        post_df = pass_full_df[['최종주소']].copy() 
        post_df.insert(0, '우편번호', ' ') 
        
        output3 = io.BytesIO()
        with pd.ExcelWriter(output3, engine='openpyxl') as writer:
            post_df.to_excel(writer, index=False, header=False, sheet_name='우체국업로드')
        excel_data3 = output3.getvalue()
        
        st.download_button(
            label="다운로드",
            data=excel_data3,
            file_name=f"{original_filename}_3_post_upload_list.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )