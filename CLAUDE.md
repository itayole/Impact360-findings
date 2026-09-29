# impact360-sav-runner webapp

- שפה: ממשק ומסמכים בעברית RTL. שמות משתנים בקוד באנגלית.
- אסור לשנות כללי חישוב (`legacy/references/rules.md`, ומומש ב-`svr/compute.py`) בלי אישור מפורש.
- כל פלט אקסל: מחרוזת המתחילה ב-"=" נכתבת כטקסט (`svr/report.py::render_xlsx`).
- אין קריאות רשת החוצה ואין ספריות/גופנים מ-CDN. הגופן (Assistant) ארוז ב-`static/fonts`.
- אין שמירת/הדפסת ערכי משיבים בלוגים. `logs/metrics.jsonl` מכיל ספירות בלבד.
- כל שינוי לוגיקה חייב לעבור את בדיקות הזהב של האגיס (`python -m pytest tests`).
- לפני כל שינוי גדול: הצג תוכנית ושאל.

## מבנה
- `svr/` — ליבה, פונקציות טהורות: `lib` (SAV+מילון+סטטיסטיקה), `profile` (זיהוי שאלות + שכבות), `compute` (חישוב), `report` (אקסל), `questionnaire` (Word), `templates` (ספריית תבניות), `preview` (Net Builder בשרת), `messages`, `accuracy` (מבחן דיוק 11.1א), `pipeline`/`cli` (עטיפות).
- `app/` — FastAPI: `main` (routes), `service` (לוגיקה), `store` (קבצים/ניקוי), `runtime` (cache + jobs).
- `static/` — frontend ללא build. `library/` — מילון ברירת מחדל (seed). `legacy/` — קוד ה-Skill המקורי (להשוואה בלבד).
- `Example/` — SAV + שאלון של האגיס (לא ב-git; ראו `.gitignore`). `tests/` נדלגים אוטומטית אם הקבצים חסרים (`GOLDEN_SAV`, `GOLDEN_DICT`).

## הרצה
- Dev: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload` (או `preview_start` עם `.claude/launch.json`).
- Docker: ראו `README.md`. גרסאות/תיוג לפי `~/.claude/CLAUDE.md` (גם `:latest` וגם `:<version>`).
- אין לעדכן גרסה (`svr/__init__.py`) בלי אישור מפורש של איתי.
