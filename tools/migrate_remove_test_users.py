"""清理遗留测试账号 alice/bob/admin 的幂等迁移脚本（仅保留 remedy_admin）"""
import os
import sqlite3
from pathlib import Path

def clean_auth(data_dir: Path):
    db = data_dir / "auth.sqlite3"
    if not db.exists():
        print(f"skip auth {db} not exist")
        return
    conn = sqlite3.connect(db)
    try:
        for name in ("alice", "bob", "admin"):
            row = conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()
            if row:
                uid = row[0]
                conn.execute("DELETE FROM tokens WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
                print(f"removed auth user {name} ({uid})")
        conn.commit()
    finally:
        conn.close()

def clean_users_db(data_dir: Path):
    # 集中库 users.db 直接 sqlite 清理，兼容无 SQLAlchemy 环境
    db = data_dir / "users.db"
    if not db.exists():
        print(f"skip users.db {db} not exist")
        return
    conn = sqlite3.connect(db)
    try:
        for uid in ("alice", "bob", "admin", "u_alice", "u_bob", "u_admin"):
            for table in ("memories", "interactions", "feedback", "personality_observations"):
                try:
                    cur = conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
                    if cur.rowcount:
                        print(f"deleted {cur.rowcount} rows {table} for {uid}")
                except sqlite3.OperationalError as e:
                    print(f"skip {table}: {e}")
            try:
                cur = conn.execute("DELETE FROM personalities WHERE user_id=?", (uid,))
                if cur.rowcount:
                    print(f"deleted {cur.rowcount} rows personalities for {uid}")
            except sqlite3.OperationalError as e:
                print(f"skip personalities: {e}")
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    data_dir = Path(os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    print(f"data_dir={data_dir.resolve()}")
    clean_auth(data_dir.resolve())
    clean_users_db(data_dir.resolve())
    print("done")
