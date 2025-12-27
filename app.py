import streamlit as st
import schedule
import time
from datetime import datetime
import pandas as pd

# ページ設定
st.set_page_config(
    page_title="定期実行スケジューラー",
    page_icon="⏰",
    layout="wide"
)

# セッション状態の初期化
if 'tasks' not in st.session_state:
    st.session_state.tasks = []
if 'execution_log' not in st.session_state:
    st.session_state.execution_log = []

# タイトル
st.title("⏰ 定期実行スケジューラー")
st.write("指定した時間に自動でタスクを実行するアプリです")

# サイドバー：タスク設定
st.sidebar.header("📝 新しいタスクを追加")

task_name = st.sidebar.text_input("タスク名", placeholder="例：価格チェック")
task_time = st.sidebar.time_input("実行時刻", value=None)
task_type = st.sidebar.selectbox(
    "タスクの種類",
    ["メッセージ表示", "データ記録", "通知"]
)
task_message = st.sidebar.text_area("実行内容", placeholder="例：Keepaで価格をチェックする")

if st.sidebar.button("➕ タスクを追加", use_container_width=True):
    if task_name and task_time:
        new_task = {
            "名前": task_name,
            "時刻": task_time.strftime("%H:%M"),
            "種類": task_type,
            "内容": task_message,
            "作成日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "状態": "待機中"
        }
        st.session_state.tasks.append(new_task)
        st.sidebar.success(f"✅ {task_name} を追加しました！")
    else:
        st.sidebar.error("❌ タスク名と時刻を入力してください")

# メインエリア：タスク一覧
st.header("📋 登録済みタスク")

if len(st.session_state.tasks) == 0:
    st.info("まだタスクが登録されていません。左のサイドバーから追加してください。")
else:
    # タブで表示
    tab1, tab2, tab3 = st.tabs(["📋 タスク一覧", "📊 実行ログ", "⚙️ 設定"])
    
    with tab1:
        # タスク一覧を表示
        for idx, task in enumerate(st.session_state.tasks):
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                
                with col1:
                    st.write(f"**{task['名前']}**")
                    st.caption(task['内容'])
                
                with col2:
                    st.write(f"⏰ {task['時刻']}")
                
                with col3:
                    if task['状態'] == "待機中":
                        st.success(task['状態'])
                    else:
                        st.info(task['状態'])
                
                with col4:
                    if st.button("🗑️", key=f"delete_{idx}"):
                        st.session_state.tasks.pop(idx)
                        st.rerun()
                
                st.divider()
        
        # 今すぐ実行ボタン
        st.subheader("🚀 手動実行")
        col1, col2 = st.columns(2)
        
        with col1:
            selected_task = st.selectbox(
                "実行するタスクを選択",
                range(len(st.session_state.tasks)),
                format_func=lambda x: st.session_state.tasks[x]['名前']
            )
        
        with col2:
            if st.button("▶️ 今すぐ実行", use_container_width=True):
                task = st.session_state.tasks[selected_task]
                log_entry = {
                    "タスク名": task['名前'],
                    "実行時刻": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "結果": "✅ 成功",
                    "メッセージ": task['内容']
                }
                st.session_state.execution_log.append(log_entry)
                st.success(f"✅ {task['名前']} を実行しました！")
    
    with tab2:
        st.subheader("📊 実行ログ")
        
        if len(st.session_state.execution_log) == 0:
            st.info("まだ実行ログがありません")
        else:
            df_log = pd.DataFrame(st.session_state.execution_log)
            st.dataframe(df_log, use_container_width=True)
            
            # CSVダウンロード
            csv = df_log.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 ログをCSVでダウンロード",
                data=csv,
                file_name=f"execution_log_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
    
    with tab3:
        st.subheader("⚙️ スケジューラー設定")
        
        st.info("""
        **💡 このアプリの使い方**
        
        1. **タスクを追加**: 左のサイドバーから新しいタスクを追加
        2. **時刻を設定**: 実行したい時刻を指定
        3. **手動実行**: 「タスク一覧」タブから今すぐ実行できます
        
        **🚀 次のステップ（レベル9以降）**
        - 実際に外部API（Keepa、Amazonなど）を呼び出す
        - LINEに自動通知する
        - Googleスプレッドシートに自動記録する
        - クラウドで24時間自動実行する
        """)
        
        st.warning("⚠️ **注意**: Streamlit Cloudでは常時実行ができません。本格的な定期実行はレベル50以降で学びます。")

# サイドバー：統計情報
st.sidebar.divider()
st.sidebar.metric("登録タスク数", len(st.session_state.tasks))
st.sidebar.metric("実行回数", len(st.session_state.execution_log))

# サンプルタスク追加ボタン
if st.sidebar.button("📝 サンプルタスクを追加", use_container_width=True):
    sample_tasks = [
        {"名前": "朝の価格チェック", "時刻": "09:00", "種類": "データ記録", "内容": "Keepaで商品価格をチェック"},
        {"名前": "在庫確認", "時刻": "14:00", "種類": "データ記録", "内容": "Amazon在庫を確認"},
        {"名前": "売上レポート", "時刻": "21:00", "種類": "通知", "内容": "今日の売上をLINEに通知"}
    ]
    
    for task in sample_tasks:
        task["作成日時"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task["状態"] = "待機中"
        st.session_state.tasks.append(task)
    
    st.sidebar.success("✅ サンプルタスクを追加しました！")
    st.rerun()
