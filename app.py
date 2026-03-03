"""
전국 공장 DB 검수 및 우편번호 자동 부여 시스템
Factory Database Inspection & Zip Code System
"""

import streamlit as st
import pandas as pd
import re
import os
import io
import requests
import concurrent.futures
from dotenv import load_dotenv
import streamlit.components.v1 as components
import urllib.parse
from typing import Optional, Tuple

# ==========================================
# 환경 설정 로드
# ==========================================
load_dotenv()
KAKAO_JS_KEY = os.getenv("KAKAO_JS_KEY")
KAKAO_REST_KEY = os.getenv("KAKAO_REST_KEY")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")

# ==========================================
# 필터링 및 정제 규칙
# ==========================================
MIN_EMPLOYEES = 15       # 최소 종업원수
MAX_EMPLOYEES = 300      # 최대 종업원수
INDUSTRY_MIN = 10        # 산업코드 시작
INDUSTRY_MAX = 34        # 산업코드 끝
APPEND_NAME = True       # 주소 뒤에 공장명 붙일지 여부

# 필수 컬럼 정의
REQUIRED_COLUMNS = ['공장명', '주소', '종업원수', '기업구분', '업종코드']
PROCESSED_MARKER = '최종주소'  # 이미 처리된 파일 감지용

# 검수 상태 정의
STATUS_PENDING = "미검수"
STATUS_PASS = "PASS"
STATUS_CLOSED = "폐업"

# ==========================================
# Streamlit 페이지 설정
# ==========================================
st.set_page_config(
    layout="wide",
    page_title="전국 공장 DB 검수기"
)

# ==========================================
# 커스텀 CSS 스타일
# ==========================================
st.markdown("""
<style>
    /* 기본 UI 요소 숨기기 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 레이아웃 최적화 */
    .block-container {
        padding-top: 2.7rem;
        padding-bottom: 2.7rem;
    }
    
    /* 버튼 스타일링 */
    .stButton > button, .stLinkButton > a {
        border-radius: 8px;
        font-weight: bold;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover, .stLinkButton > a:hover {
        border-color: #FF4B4B;
        color: #FF4B4B;
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    
    /* 구분선 스타일 - 섹션 구분 강화 */
    hr {
        margin-top: 1.2em !important;
        margin-bottom: 1.2em !important;
        border-color: #e0e0e0 !important;
    }
    
    /* 컬럼 간격 조정 */
    [data-testid="column"] [data-testid="stVerticalBlock"] {
        gap: 0.8rem !important;
    }
    
    /* 메트릭 카드 스타일 개선 */
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
    
    /* 헤더 여백 축소 */
    h5 {
        margin-top: 0.5rem !important;
        margin-bottom: 0.3rem !important;
    }
    
    /* 버튼 패딩 축소 */
    .stButton > button {
        padding: 0.25rem 0.5rem !important;
    }
    
    /* 텍스트 영역 여백 축소 */
    .stTextArea > div > div {
        padding: 0.25rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 유틸리티 함수들
# ==========================================

def validate_environment() -> bool:
    """환경 변수 검증"""
    if not KAKAO_JS_KEY:
        st.error("KAKAO_JS_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return False
    if not KAKAO_REST_KEY:
        st.error("KAKAO_REST_KEY가 설정되지 않았습니다. 우편번호 기능이 제한됩니다.")
    if not ACCESS_PASSWORD:
        st.error("ACCESS_PASSWORD가 설정되지 않았습니다. .env 파일을 확인해주세요.")
        return False
    return True

def validate_dataframe(df: pd.DataFrame) -> Tuple[bool, str]:
    """데이터프레임 유효성 검사"""
    if PROCESSED_MARKER in df.columns:
        return True, "processed"
    
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"필수 컬럼이 누락되었습니다: {', '.join(missing_cols)}"
    
    return True, "original"

def check_industry_code(code) -> bool:
    """산업코드 유효성 검사"""
    if pd.isna(code):
        return False
    try:
        code_str = str(code).split(',')[0].strip()[:2]
        if not code_str.isdigit():
            return False
        code_num = int(code_str)
        return INDUSTRY_MIN <= code_num <= INDUSTRY_MAX
    except (ValueError, IndexError):
        return False

def clean_address(row: pd.Series) -> pd.Series:
    """주소 정제 및 분리 (검색용/최종용)"""
    addr = str(row['주소'])
    name = str(row['공장명'])
    
    base_addr = addr
    while re.search(r'\([^()]*\)', base_addr):
        base_addr = re.sub(r'\([^()]*\)', '', base_addr)
    
    base_addr = base_addr.replace('(', '').replace(')', '')
    base_addr = re.sub(r'외\s?\d*필지.*', '', base_addr)
    base_addr = re.sub(r'외\s?\d*.*', '', base_addr)
    
    search_addr = base_addr
    search_addr = re.sub(r'[,.\s]*\d+[-~]?\d*호.*', '', search_addr)
    search_addr = re.sub(r'[,.\s]*\d+층.*', '', search_addr)
    search_addr = re.sub(r',\s*\d+.*', '', search_addr)
    search_addr = re.sub(r'\s+', ' ', search_addr).strip().rstrip(',')
    
    final_addr = re.sub(r'\s+', ' ', base_addr).strip().rstrip(',')
    
    if APPEND_NAME:
        final_addr = f"{final_addr} {name}"
    
    return pd.Series([search_addr, final_addr])

def load_and_filter(file) -> Optional[pd.DataFrame]:
    """파일 로드 및 필터링 처리"""
    try:
        file.seek(0)
        if file.name.endswith('.xlsx'):
            df = pd.read_excel(file, engine='openpyxl')
        else:
            df = pd.read_csv(file, encoding='utf-8-sig')
        
        st.info(f"파일 정보: {len(df)}행 x {len(df.columns)}열 감지됨")
        is_valid, status = validate_dataframe(df)
        
        if not is_valid:
            st.warning("첫 번째 행을 헤더로 읽기 실패. 두 번째 행을 헤더로 재시도합니다...")
            file.seek(0)
            if file.name.endswith('.xlsx'):
                df = pd.read_excel(file, header=1, engine='openpyxl')
            else:
                df = pd.read_csv(file, header=1, encoding='utf-8-sig')
            
            df.columns = df.columns.str.strip()
            st.info(f"재읽기 결과: {len(df)}행 x {len(df.columns)}열")
            st.info(f"감지된 컬럼: {', '.join(df.columns.tolist()[:10])}{'...' if len(df.columns) > 10 else ''}")
            
            is_valid, status = validate_dataframe(df)
            if not is_valid:
                st.error(f"파일 검증 실패: {status}")
                st.error(f"현재 컬럼: {list(df.columns)[:10]}")
                return None
        
        if status == "processed":
            if '검수결과' not in df.columns:
                df['검수결과'] = STATUS_PENDING
            st.success(f"이전 작업 파일을 불러왔습니다 ({len(df):,}건)")
            return df.reset_index(drop=True)
        
        with st.spinner('데이터 필터링 중...'):
            initial_count = len(df)
            
            before_address_filter = len(df)
            df['주소'] = df['주소'].astype(str).str.strip()
            df = df[df['주소'].notna() & (df['주소'] != '') & (df['주소'] != 'nan')]
            after_address_filter = len(df)
            
            df['종업원수'] = pd.to_numeric(df['종업원수'], errors='coerce')
            before_employee_filter = len(df)
            df = df[(df['종업원수'] >= MIN_EMPLOYEES) & (df['종업원수'] <= MAX_EMPLOYEES)]
            after_employee_filter = len(df)
            
            before_company_filter = len(df)
            df = df[df['기업구분'].str.contains('소기업|중기업', na=False, regex=True)]
            after_company_filter = len(df)
            
            before_industry_filter = len(df)
            df = df[df['업종코드'].apply(check_industry_code)]
            filtered_count = len(df)
            
            st.info(f"""
            **필터링 결과:**
            - 원본 데이터: {initial_count:,}건
            - 주소 필터링 (주소 있음): {before_address_filter:,}건 → {after_address_filter:,}건 ({before_address_filter - after_address_filter:,}건 제외)
            - 종업원수 필터링 ({MIN_EMPLOYEES}~{MAX_EMPLOYEES}명): {before_employee_filter:,}건 → {after_employee_filter:,}건 ({before_employee_filter - after_employee_filter:,}건 제외)
            - 기업구분 필터링 (소/중기업): {before_company_filter:,}건 → {after_company_filter:,}건 ({before_company_filter - after_company_filter:,}건 제외)
            - 산업코드 필터링 ({INDUSTRY_MIN}~{INDUSTRY_MAX}): {before_industry_filter:,}건 → {filtered_count:,}건 ({before_industry_filter - filtered_count:,}건 제외)
            - **최종 결과: {filtered_count:,}건**
            """)
            
            if filtered_count == 0:
                st.error("필터링 조건에 맞는 데이터가 없습니다. 필터링 설정을 확인해주세요.")
                return None
        
        with st.spinner('주소 정제 중...'):
            df[['검색용주소', '최종주소']] = df.apply(clean_address, axis=1)
            before_dedup = len(df)
            df = df.drop_duplicates(subset=['검색용주소'], keep='first')
            after_dedup = len(df)
            if before_dedup > after_dedup:
                st.success(f"동일 주소 중복 데이터 {before_dedup - after_dedup:,}건 제거 완료")
        
        df['검수결과'] = STATUS_PENDING
        df = df.sort_values(by='검색용주소').reset_index(drop=True)
        st.success("주소 가나다순 정렬 완료")
        
        return df
        
    except Exception as e:
        st.error(f"파일 처리 중 오류가 발생했습니다: {str(e)}")
        return None

def create_excel_download(df: pd.DataFrame, sheet_name: str = 'Sheet1') -> bytes:
    """엑셀 파일 생성"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()

def create_excel_download_no_header(df: pd.DataFrame, sheet_name: str = 'Sheet1') -> bytes:
    """컬럼명 없이 엑셀 파일 생성 (우체국용)"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, header=False, sheet_name=sheet_name)
    return output.getvalue()

@st.cache_data(show_spinner=False)
def get_progress_stats(df_hash: str, total: int, status_counts: tuple) -> dict:
    """진행 상황 통계 계산 (캐시 적용)"""
    pending, pass_cnt, closed_cnt = status_counts
    done = total - pending
    progress = int(done / total * 100) if total > 0 else 0
    return {
        'total': total,
        'done': done,
        'pass': pass_cnt,
        'closed': closed_cnt,
        'progress': progress
    }

def compute_stats(df: pd.DataFrame) -> dict:
    """통계 계산을 위한 래퍼 함수"""
    total = len(df)
    status_series = df['검수결과'].value_counts()
    pending = status_series.get(STATUS_PENDING, 0)
    pass_cnt = status_series.get(STATUS_PASS, 0)
    closed_cnt = status_series.get(STATUS_CLOSED, 0)
    df_hash = f"{total}_{pending}_{pass_cnt}_{closed_cnt}"
    return get_progress_stats(df_hash, total, (pending, pass_cnt, closed_cnt))

def get_zipcode_from_kakao(address: str) -> tuple:
    """카카오 API를 통한 우편번호 및 정확한 주소 추출"""
    if not KAKAO_REST_KEY:
        return ("", "")
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    search_query = address.split(',')[0].strip()
    
    try:
        res = requests.get(url, headers=headers, params={"query": search_query}, timeout=3)
        if res.status_code == 200:
            docs = res.json().get("documents", [])
            if docs:
                road_addr = docs[0].get("road_address")
                if road_addr and road_addr.get("zone_no"):
                    zipcode = road_addr.get("zone_no")
                    address_name = road_addr.get("address_name")
                    return (zipcode, address_name)
    except:
        pass
    return ("검색실패", "")

# ==========================================
# 인증 시스템
# ==========================================
if not validate_environment():
    st.stop()

if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.write("<br><br><br><br>", unsafe_allow_html=True)
    spacer1, login_col, spacer2 = st.columns([1, 1.5, 1])
    
    with login_col:
        st.markdown("<h3 style='text-align: center;'>로그인</h3>", unsafe_allow_html=True)
        st.info("비밀번호를 입력해주세요.")
        pwd = st.text_input("접속 비밀번호", type="password", key="login_pwd")
        
        if pwd:
            if pwd == ACCESS_PASSWORD:
                st.session_state.auth = True
                st.success("인증 성공!")
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    st.stop()

# ==========================================
# 사이드바 네비게이션
# ==========================================
st.sidebar.title("메뉴 선택")
menu = st.sidebar.radio("", ["1. 공장 DB 검수", "2. 우편번호 자동 부여"])

st.sidebar.divider()
st.sidebar.info("Tip: 1번 메뉴에서 검수를 완료하고 다운로드한 엑셀 파일을 2번 메뉴에 업로드하여 우편번호를 부여하세요.")

# ====================================================================================
# [메뉴 1] 공장 DB 검수
# ====================================================================================
if menu == "1. 공장 DB 검수":
    spacer_left, center_col, spacer_right = st.columns([1, 2, 1])
    with center_col:
        st.title("전국 공장 DB 검수 시스템")
        uploaded_file = st.file_uploader(
            "공장 DB 파일을 업로드하세요",
            type=['csv', 'xlsx'],
            help="CSV 또는 XLSX 형식의 파일을 업로드해주세요."
        )

    if uploaded_file:
        if "history" not in st.session_state:
            st.session_state.history = []
        
        if "current_file" not in st.session_state or st.session_state.current_file != uploaded_file.name:
            with st.spinner('파일 처리 중...'):
                st.session_state.df = load_and_filter(uploaded_file)
                st.session_state.current_file = uploaded_file.name
                st.session_state.history = []
                st.session_state.df_changed = True
        
        df = st.session_state.df
        
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            st.warning("유효한 데이터가 없습니다. 파일을 다시 업로드해주세요.")
            if "current_file" in st.session_state:
                del st.session_state["current_file"]
            st.stop()
        
        st.divider()
        
        stats = compute_stats(df)
        col1, col2, col3, col4, dash_spacer = st.columns([1, 1, 1, 1, 1])
        
        col1.metric("전체 타겟", f"{stats['total']:,}건")
        col2.metric("검수 진행", f"{stats['done']:,}건", f"{stats['progress']}%")
        col3.metric("PASS", f"{stats['pass']:,}건")
        col4.metric("폐업", f"{stats['closed']:,}건")
        
        if stats['total'] > 0:
            st.progress(stats['progress'] / 100)
        
        st.divider()

        left_col, right_col = st.columns([1, 2], gap="large")
        with left_col:
            st.subheader("검수 리스트")
            pending_df = df[df['검수결과'] == STATUS_PENDING]
            
            if not pending_df.empty:
                target_idx = pending_df.index[0]
                target_row = df.iloc[target_idx]
                
                remaining = len(pending_df)
                st.info(f"**{target_row['공장명']}** (남은 검수: {remaining:,}건)")
                st.markdown(f"{target_row['최종주소']}")
                
                if '종업원수' in target_row:
                    st.caption(f"종업원수: {target_row['종업원수']}명")
                
                st.write("---")
                
                title_col1, title_col2 = st.columns(2)
                with title_col1:
                    st.markdown("##### PASS")
                    st.caption("확인 완료 누를 시 주소+업체명, 업체명 제외 누를 시 주소만")
                with title_col2:
                    st.markdown("##### 검수제외")
                    st.caption("폐업/철거 클릭 후 추후에 재차 확인 가능")
                
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if st.button("확인 완료", use_container_width=True, key="pass_default"):
                        st.session_state.history.append(target_idx)
                        current_addr = st.session_state.df.at[target_idx, '최종주소']
                        factory_name = target_row['공장명']
                        if not current_addr.endswith(factory_name):
                            st.session_state.df.at[target_idx, '최종주소'] = f"{current_addr.rstrip()} {factory_name}"
                        st.session_state.df.at[target_idx, '검수결과'] = STATUS_PASS
                        st.rerun()
                    
                    if st.button("업체명 제외", use_container_width=True, key="pass_no_name"):
                        st.session_state.history.append(target_idx)
                        current_addr = st.session_state.df.at[target_idx, '최종주소']
                        factory_name = target_row['공장명']
                        if current_addr.endswith(factory_name):
                            st.session_state.df.at[target_idx, '최종주소'] = current_addr[:-len(factory_name)].rstrip()
                        st.session_state.df.at[target_idx, '검수결과'] = STATUS_PASS
                        st.rerun()

                with btn_col2:
                    if st.button("폐업/철거", use_container_width=True, key="btn_closed"):
                        st.session_state.history.append(target_idx)
                        st.session_state.df.at[target_idx, '검수결과'] = STATUS_CLOSED
                        st.session_state.df_changed = True
                        st.rerun()
                    
                    if st.button("이전 취소", disabled=len(st.session_state.history) == 0, use_container_width=True, key="btn_undo"):
                        last_idx = st.session_state.history.pop()
                        st.session_state.df.at[last_idx, '검수결과'] = STATUS_PENDING
                        st.session_state.df_changed = True
                        st.rerun()

                st.write("---")
                
                row2_col1, row2_col2 = st.columns(2)
                with row2_col1:
                    st.markdown("##### 임시 저장")
                    if st.button("백업 파일 준비하기", use_container_width=True, key=f"btn_prepare_{target_idx}"):
                        with st.spinner("엑셀 파일을 만들고 있습니다..."):
                            backup_data = create_excel_download(st.session_state.df, '중간저장')
                            safe_filename = os.path.splitext(st.session_state.current_file)[0]
                            st.download_button(
                                label="다운로드",
                                data=backup_data,
                                file_name=f"{safe_filename}_backup.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                                key=f"btn_dl_{target_idx}"
                            )
                
                with row2_col2:
                    st.markdown("##### 외부지도")
                    search_addr_encoded = urllib.parse.quote(target_row['검색용주소'])
                    map_col1, map_col2 = st.columns(2)
                    with map_col1:
                        st.link_button("카카오", url=f"https://map.kakao.com/?q={search_addr_encoded}", use_container_width=True)
                    with map_col2:
                        st.link_button("네이버", url=f"https://map.naver.com/p/search/{search_addr_encoded}", use_container_width=True)
                
                st.write("---")

                st.markdown("##### 주소수정")
                st.caption("새로운 주소로 우편용 주소가 변경")
                edited_address = st.text_area(
                    "최종주소",
                    value=target_row['최종주소'],
                    height=60,
                    key=f"addr_edit_{target_idx}",
                    label_visibility="collapsed"
                )
                
                addr_col1, addr_col2 = st.columns(2)
                if addr_col1.button("저장", use_container_width=True, key="btn_save_addr"):
                    if edited_address.strip() and edited_address != target_row['최종주소']:
                        st.session_state.df.at[target_idx, '최종주소'] = edited_address.strip()
                        st.session_state.df_changed = True
                        st.success("저장완료")
                        st.rerun()
                    elif not edited_address.strip():
                        st.error("주소입력 필요")
                    else:
                        st.info("변경없음")
                
                if addr_col2.button("복구", use_container_width=True, key="btn_reset_addr"):
                    st.session_state.df.at[target_idx, '최종주소'] = target_row['검색용주소'] + (' ' + target_row['공장명'] if APPEND_NAME else '')
                    st.session_state.df_changed = True
                    st.success("복구완료")
                    st.rerun()
            else:
                st.success("모든 검수가 완료되었습니다!")
        
        with right_col:
            if not pending_df.empty:
                search_addr = target_row['검색용주소']
                encoded_addr = urllib.parse.quote(search_addr)
                map_url = f"https://inkkadiis.github.io/ED-DB_project/static/map.html?addr={encoded_addr}&key={KAKAO_JS_KEY}"
                components.iframe(map_url, height=900, scrolling=False)
            else:
                st.info("검수할 항목이 없습니다.")
        
        st.divider()
        st.subheader("데이터 다운로드")
        
        original_filename = os.path.splitext(st.session_state.current_file)[0]
        d_col1, d_col2, d_col3, d_col4 = st.columns(4, gap="medium")
        
        with d_col1:
            st.markdown("##### 클리닝 원본")
            st.caption("필터링 및 정제 완료된 전체 데이터")
            if st.button("파일 생성하기", key="btn_prep_1", use_container_width=True):
                with st.spinner("엑셀 생성 중..."):
                    df_download_1 = df.drop(columns=['검수결과'], errors='ignore')
                    excel_data1 = create_excel_download(df_download_1, '클리닝완료_전체')
                    st.download_button(
                        label="다운로드",
                        data=excel_data1,
                        file_name=f"{original_filename}_1_cleaned.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="dl_btn_1"
                    )
        
        with d_col2:
            st.markdown("##### PASS 목록")
            st.caption("검수 완료된 가동중인 공장")
            if st.button("파일 생성하기", key="btn_prep_2", use_container_width=True):
                with st.spinner("엑셀 생성 중..."):
                    pass_df = df[df['검수결과'] == STATUS_PASS].copy()
                    if pass_df.empty:
                        st.error("PASS 처리된 데이터가 없습니다.")
                    else:
                        df_download_2 = pass_df.drop(columns=['검수결과'], errors='ignore')
                        excel_data2 = create_excel_download(df_download_2, 'PASS_완료')
                        st.download_button(
                            label="다운로드",
                            data=excel_data2,
                            file_name=f"{original_filename}_2_pass.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="dl_btn_2"
                        )
        
        with d_col3:
            st.markdown("##### 우체국용")
            st.caption("주소만 (헤더 없음)")
            if st.button("파일 생성하기", key="btn_prep_3", use_container_width=True):
                with st.spinner("엑셀 생성 중..."):
                    pass_df = df[df['검수결과'] == STATUS_PASS].copy()
                    if pass_df.empty:
                        st.error("PASS 처리된 데이터가 없습니다.")
                    else:
                        post_df = pass_df[['최종주소']].copy()
                        excel_data3 = create_excel_download_no_header(post_df, '우체국업로드')
                        st.download_button(
                            label="다운로드",
                            data=excel_data3,
                            file_name=f"{original_filename}_3_post.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="dl_btn_3"
                        )
        
        with d_col4:
            st.markdown("##### 제외 목록")
            st.caption("폐업/철거로 제외된 공장")
            if st.button("파일 생성하기", key="btn_prep_4", use_container_width=True):
                with st.spinner("엑셀 생성 중..."):
                    closed_df = df[df['검수결과'] == STATUS_CLOSED].copy()
                    if closed_df.empty:
                        st.error("제외 처리된 데이터가 없습니다.")
                    else:
                        df_download_4 = closed_df.drop(columns=['검수결과'], errors='ignore')
                        excel_data4 = create_excel_download(df_download_4, '제외_목록')
                        st.download_button(
                            label="다운로드",
                            data=excel_data4,
                            file_name=f"{original_filename}_4_excluded.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="dl_btn_4"
                        )

    else:
        spacer_left, center_col, spacer_right = st.columns([1, 2, 1])
        with center_col:
            st.info("파일을 업로드하여 검수를 시작하세요.")
            with st.expander("사용 방법"):
                st.markdown(f"""
                ### 사용 방법
                1. **파일 업로드**: 공장 DB 파일(CSV 또는 XLSX)을 업로드합니다.
                2. **자동 필터링**: 설정된 조건에 따라 자동으로 데이터가 필터링됩니다.
                3. **지도 검수**: 각 공장의 위치를 지도에서 확인하며 검수합니다.
                4. **검수 처리**: PASS 또는 폐업/철거로 분류합니다.
                5. **데이터 다운로드**: 검수 완료 후 필요한 형식으로 다운로드합니다.
                
                ### 필터링 조건
                - 종업원수: {MIN_EMPLOYEES}명 ~ {MAX_EMPLOYEES}명
                - 기업구분: 소기업, 중기업
                - 산업코드: {INDUSTRY_MIN} ~ {INDUSTRY_MAX}
                """)

# ====================================================================================
# [메뉴 2] 우편번호 수기 검증 시스템
# ====================================================================================
elif menu == "2. 우편번호 자동 부여":
    spacer_left, center_col, spacer_right = st.columns([1, 2, 1])
    with center_col:
        st.title("우편번호 수기 검증 시스템")
        st.caption("우체국 프로그램에서 받은 파일(1열:우편번호, 3열:주소)을 업로드하세요.")
        zip_file = st.file_uploader("우체국 결과 파일을 업로드하세요", type=['csv', 'xlsx', 'xls'], key="upload_zip")

    if zip_file:
        # 파일 초기 로드
        if "zip_file" not in st.session_state or st.session_state.zip_file != zip_file.name:
            st.session_state.zip_file = zip_file.name
            try:
                if zip_file.name.endswith('.xlsx'):
                    df_zip = pd.read_excel(zip_file, engine='openpyxl', header=None)
                elif zip_file.name.endswith('.xls'):
                    df_zip = pd.read_excel(zip_file, engine='xlrd', header=None)
                else:
                    df_zip = pd.read_csv(zip_file, header=None)
                
                # [수정] 1열(인덱스 0)과 3열(인덱스 2)만 추출
                df_zip = df_zip.iloc[:, [0, 2]]
                df_zip.columns = ['우편번호', '주소']
                
                # 첫 번째 행이 헤더인 경우 제거 (우편번호 컬럼 값이 '우편번호'인 경우)
                if not df_zip.empty and str(df_zip.iloc[0]['우편번호']).strip() in ['우편번호', 'zipcode', '郵便番号']:
                    df_zip = df_zip.iloc[1:].reset_index(drop=True)
                
                # 빈 값(NaN) 처리 및 문자열 변환
                df_zip['우편번호'] = df_zip['우편번호'].fillna('').astype(str).str.strip()
                df_zip['주소'] = df_zip['주소'].fillna('').astype(str).str.strip()
                
                # '.0' 같은 소수점 찌꺼기 제거
                df_zip['우편번호'] = df_zip['우편번호'].apply(lambda x: x.split('.')[0] if '.' in x else x)
                
                # 검증 상태 추가 (우편번호가 있으면 '완료', 없으면 '대기')
                df_zip['검증상태'] = '대기'
                df_zip.loc[df_zip['우편번호'] != '', '검증상태'] = '완료'
                
                st.session_state.zip_df = df_zip
                st.session_state.zip_history = []
                
                st.success(f"파일 로드 완료: {len(df_zip)}건")
            except Exception as e:
                st.error(f"파일 로드 실패: {str(e)}")
                st.stop()

        z_df = st.session_state.zip_df
        
        # 통계 계산
        total = len(z_df)
        completed = len(z_df[z_df['검증상태'] == '완료'])
        pending = len(z_df[z_df['검증상태'] == '대기'])
        removed = len(z_df[z_df['검증상태'] == '제외']) # [수정] 건너뜀 -> 제외로 변경
        
        st.divider()
        z_col1, z_col2, z_col3, z_col4 = st.columns(4)
        z_col1.metric("전체", f"{total}건")
        z_col2.metric("완료", f"{completed}건")
        z_col3.metric("대기 중", f"{pending}건")
        z_col4.metric("제외됨", f"{removed}건") # [수정] 라벨 변경
        
        if total > 0:
            progress = int(completed / total * 100)
            st.progress(progress / 100)
        
        st.divider()

        # 대기 중인 항목이 있으면 수기 검증 UI
        pending_df = z_df[z_df['검증상태'] == '대기']
        
        if not pending_df.empty:
            target_idx = pending_df.index[0]  # 원본 엑셀의 고유 행 번호
            target_row = z_df.iloc[target_idx]
            
            left_col, right_col = st.columns([1, 2], gap="large")
            
            with left_col:
                st.subheader("검수 리스트")
                remaining = len(pending_df)
                st.info(f"**{target_row['주소'][:50]}{'...' if len(target_row['주소']) > 50 else ''}** (남은 검수: {remaining:,}건)")
                st.markdown(f"{target_row['주소']}")
                
                st.write("---")
                
                title_col1, title_col2 = st.columns(2)
                with title_col1:
                    st.markdown("##### 우편번호 검증")
                    st.caption("우편번호 입력 후 저장 버튼을 누르세요")
                with title_col2:
                    st.markdown("##### 검증 제외")
                    st.caption("자동 검색시 주소에서 업체명 자동 제거")
                
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    # 자동 검색된 우편번호를 위한 session state 확인
                    searched_zip_key = f"searched_zip_{target_idx}"
                    widget_update_key = st.session_state.get(f"widget_update_{target_idx}", 0)
                    default_zip = st.session_state.get(searched_zip_key, "")
                    
                    # Widget key를 동적으로 변경하여 value 업데이트 강제
                    zip_input_key = f"zipcode_{target_idx}_{widget_update_key}"
                    zipcode_input = st.text_input(
                        "우편번호 (5자리)",
                        max_chars=5,
                        value=default_zip,
                        key=zip_input_key,
                        placeholder="12345",
                        label_visibility="collapsed"
                    )
                    
                    if st.button("저장", use_container_width=True, key="btn_save", type="primary"):
                        if zipcode_input.strip() and len(zipcode_input.strip()) == 5:
                            st.session_state.zip_history.append(target_idx)
                            # 주소 수정란의 현재 값을 동적 key로 가져오기
                            addr_update_key_val = st.session_state.get(f"addr_update_{target_idx}", 0)
                            addr_widget_key_current = f"addr_{target_idx}_{addr_update_key_val}"
                            saved_address = st.session_state.get(addr_widget_key_current, target_row['주소'])
                            
                            st.session_state.zip_df.at[target_idx, '우편번호'] = zipcode_input.strip()
                            st.session_state.zip_df.at[target_idx, '주소'] = saved_address.strip() if saved_address else target_row['주소']
                            st.session_state.zip_df.at[target_idx, '검증상태'] = '완료'
                            # 검색된 정보 초기화
                            if searched_zip_key in st.session_state:
                                del st.session_state[searched_zip_key]
                            if f"widget_update_{target_idx}" in st.session_state:
                                del st.session_state[f"widget_update_{target_idx}"]
                            if f"searched_addr_{target_idx}" in st.session_state:
                                del st.session_state[f"searched_addr_{target_idx}"]
                            if f"addr_update_{target_idx}" in st.session_state:
                                del st.session_state[f"addr_update_{target_idx}"]
                            st.rerun()
                        else:
                            st.error("5자리 우편번호를 입력해주세요!")
                    
                    if st.button("이전 취소", disabled=len(st.session_state.get('zip_history', [])) == 0, 
                                use_container_width=True, key="btn_undo"):
                        last_idx = st.session_state.zip_history.pop()
                        st.session_state.zip_df.at[last_idx, '검증상태'] = '대기'
                        st.session_state.zip_df.at[last_idx, '우편번호'] = ''
                        # 해당 항목의 검색 결과도 초기화
                        searched_zip_key_prev = f"searched_zip_{last_idx}"
                        if searched_zip_key_prev in st.session_state:
                            del st.session_state[searched_zip_key_prev]
                        if f"widget_update_{last_idx}" in st.session_state:
                            del st.session_state[f"widget_update_{last_idx}"]
                        st.rerun()

                with btn_col2:
                    if st.button("🔍 우편번호 자동 검색", use_container_width=True):
                        with st.spinner("우편번호 검색 중..."):
                            searched_zip, searched_addr = get_zipcode_from_kakao(target_row['주소'])
                            if searched_zip and searched_zip != "검색실패":
                                # 검색 성공 시 우편번호 입력 필드와 주소 수정란에 모두 표시
                                st.session_state[searched_zip_key] = searched_zip
                                st.session_state[f"searched_addr_{target_idx}"] = searched_addr
                                st.session_state[f"widget_update_{target_idx}"] = widget_update_key + 1
                                st.session_state[f"addr_update_{target_idx}"] = widget_update_key + 1
                                st.success(f"우편번호 {searched_zip} 검색 성공! 주소 수정란을 확인하세요.")
                                st.rerun()
                            else:
                                st.error("우편번호를 찾지 못했습니다. 수동으로 입력하거나 주소를 수정해주세요.")
                    
                    if st.button("목록에서 제거", use_container_width=True, key="btn_remove"):
                        st.session_state.zip_history.append(target_idx)
                        st.session_state.zip_df.at[target_idx, '검증상태'] = '제외'
                        st.rerun()
                
                st.write("---")
                
                row2_col1, row2_col2 = st.columns(2)
                with row2_col1:
                    st.markdown("##### 💡 안내")
                    st.caption("필요할 경우 주소 수정란에 업체명 수기 입력 후 저장. 우편번호 자동 검색이 안될 경우 목록에서 제거")
                
                with row2_col2:
                    st.markdown("##### 외부지도")
                    search_addr_encoded = urllib.parse.quote(target_row['주소'])
                    map_col1, map_col2 = st.columns(2)
                    with map_col1:
                        st.link_button("카카오", url=f"https://map.kakao.com/?q={search_addr_encoded}", use_container_width=True)
                    with map_col2:
                        st.link_button("네이버", url=f"https://map.naver.com/p/search/{search_addr_encoded}", use_container_width=True)
                
                st.write("---")

                st.markdown("##### 주소수정")
                st.caption("새로운 주소로 우편용 주소가 변경")
                
                # 자동 검색된 주소 확인
                addr_update_key = st.session_state.get(f"addr_update_{target_idx}", 0)
                searched_address = st.session_state.get(f"searched_addr_{target_idx}", "")
                default_address = searched_address if searched_address else target_row['주소']
                
                # Widget key를 동적으로 변경하여 value 업데이트 강제
                addr_widget_key = f"addr_{target_idx}_{addr_update_key}"
                edited_address = st.text_area(
                    "최종주소",
                    value=default_address,
                    height=60,
                    key=addr_widget_key,
                    label_visibility="collapsed"
                )
                
                addr_col1, addr_col2 = st.columns(2)
                if addr_col1.button("저장", use_container_width=True, key="btn_save_addr_zip"):
                    if edited_address.strip() and edited_address != target_row['주소']:
                        st.session_state.zip_df.at[target_idx, '주소'] = edited_address.strip()
                        # 검색된 주소 정보 초기화
                        if f"searched_addr_{target_idx}" in st.session_state:
                            del st.session_state[f"searched_addr_{target_idx}"]
                        if f"addr_update_{target_idx}" in st.session_state:
                            del st.session_state[f"addr_update_{target_idx}"]
                        st.success("저장완료")
                        st.rerun()
                    elif not edited_address.strip():
                        st.error("주소입력 필요")
                    else:
                        st.info("변경없음")
                
                if addr_col2.button("복구", use_container_width=True, key="btn_reset_addr_zip"):
                    # 원본 주소로 복구 및 검색 결과 초기화
                    if f"searched_addr_{target_idx}" in st.session_state:
                        del st.session_state[f"searched_addr_{target_idx}"]
                    if f"addr_update_{target_idx}" in st.session_state:
                        del st.session_state[f"addr_update_{target_idx}"]
                    st.success("복구완료")
                    st.rerun()
            
            with right_col:
                # 자동 검색된 주소가 있으면 그 주소로 지도 표시, 없으면 원본 주소
                display_address = st.session_state.get(f"searched_addr_{target_idx}", target_row['주소'])
                encoded_addr = urllib.parse.quote(display_address)
                map_url = f"https://inkkadiis.github.io/ED-DB_project/static/map.html?addr={encoded_addr}&key={KAKAO_JS_KEY}"
                components.iframe(map_url, height=900, scrolling=False)
        else:
            st.success("모든 검수가 완료되었습니다!")
        
        st.divider()
        st.subheader("데이터 다운로드")
        
        # 최종 데이터 준비 (완료된 것만 가져와서 주소 기준으로 정렬)
        final_df = z_df[z_df['검증상태'] == '완료'][['우편번호', '주소']].copy()
        final_df = final_df.sort_values(by='주소').reset_index(drop=True)
        
        original_filename = os.path.splitext(st.session_state.zip_file)[0]
        
        spacer_left, center_col, spacer_right = st.columns([1, 1, 1])
        with center_col:
            st.markdown("##### 우편번호 최종본")
            st.caption("우편번호, 주소 (헤더 포함) - 주소 기준 정렬")
            st.info(f"다운로드 가능: {len(final_df):,}건 (제외된 항목 제외)")
            
            if len(final_df) > 0:
                if st.button("파일 생성하기", use_container_width=True, key="btn_prep_final"):
                    with st.spinner("최종 엑셀 생성 중..."):
                        excel_data = create_excel_download(final_df, '최종우편번호')
                        st.download_button(
                            label="다운로드",
                            data=excel_data,
                            file_name=f"{original_filename}_최종완료.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="dl_btn_final"
                        )
            else:
                st.warning("다운로드할 데이터가 없습니다.")
