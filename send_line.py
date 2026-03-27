"""LINE送信スクリプト（GitHub Actions用）"""

import os
import json
import time
import requests
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROGRESS_PATH = SCRIPT_DIR / "カリキュラム" / "progress.json"
CURRICULUM_PATH = SCRIPT_DIR / "カリキュラム" / "curriculum.json"
DOCS_AUDIO_DIR = SCRIPT_DIR / "docs" / "audio"

TOKEN = os.environ.get("LINE_CHANNEL_TOKEN", "")
USER_ID = os.environ.get("LINE_USER_ID", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")


def get_lesson_info():
    """進捗とカリキュラムからレッスン情報を取得"""
    progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    day = progress.get("last_completed_day", 1)

    curriculum = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
    for phase in curriculum["phases"]:
        for lesson in phase["lessons"]:
            if lesson["day"] == day:
                return day, lesson["title"], phase["title"]
    return day, "不明", "不明"


def get_latest_audio():
    """最新の音声ファイルを取得"""
    mp3_files = sorted(DOCS_AUDIO_DIR.glob("Day*.mp3"), reverse=True)
    return mp3_files[0] if mp3_files else None


def send_line(messages):
    """LINE push message"""
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        json={"to": USER_ID, "messages": messages},
    )
    return resp


def main():
    if not TOKEN or not USER_ID:
        print("LINE設定なし — スキップ")
        return

    day, title, phase = get_lesson_info()
    audio_file = get_latest_audio()

    if not audio_file:
        print("音声ファイルが見つかりません")
        return

    # 音声URL構築
    repo_owner, repo_name = REPO.split("/")
    audio_url = f"https://{repo_owner}.github.io/{repo_name}/audio/{audio_file.name}"

    # ファイルサイズからduration概算
    size = audio_file.stat().st_size
    duration_ms = int(size * 8 / 32000 * 1000)

    # GitHub Pagesデプロイ確認（リトライ）
    for i in range(3):
        try:
            status = requests.head(audio_url, timeout=10).status_code
            if status == 200:
                print(f"音声URL確認OK: {audio_url}")
                break
        except Exception:
            pass
        print(f"Pages未デプロイ、30秒待機... ({i+1}/3)")
        time.sleep(30)

    # 音声メッセージ送信
    resp = send_line([
        {
            "type": "text",
            "text": f"📻 株式投資ラジオ Day {day}/90\n\n📖 {title}\n🎯 {phase}\n\n▶ 下の音声を再生してください",
        },
        {
            "type": "audio",
            "originalContentUrl": audio_url,
            "duration": duration_ms,
        },
    ])

    if resp.status_code == 200:
        print("LINE送信完了!")
    else:
        print(f"音声送信失敗: {resp.text}")
        # テキストのみフォールバック
        send_line([
            {
                "type": "text",
                "text": f"📻 株式投資ラジオ Day {day}/90\n\n📖 {title}\n\n🎧 音声: {audio_url}",
            }
        ])
        print("テキストのみ送信完了")


if __name__ == "__main__":
    main()
