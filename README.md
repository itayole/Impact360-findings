# Impact360 SAV Runner

אפליקציית ווב פנימית (container אחד) להרצת ממצאי Impact360 מקובץ SAV: העלאה → אישור התאמות → הרצה → אקסל RTL.
האפיון המלא: [Impact360_SAV_Runner_WebApp_SPEC.md](Impact360_SAV_Runner_WebApp_SPEC.md). מדריך משתמש: [docs/USER_GUIDE_HE.md](docs/USER_GUIDE_HE.md).

## פיתוח
```bash
pip install -r requirements-dev.txt
python -m pytest tests                                   # בדיקות זהב (צריך Example/ עם ה-SAV) + API + יחידה
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
python -m svr.cli profile "Example/15422 (ID 147851).sav" --dictionary "library/Impact360 import dictionary (ID 145212).xlsx" --brand "האגיס" --out mapping.json
python -m svr.cli run "Example/15422 (ID 147851).sav" mapping.json --out Findings.xlsx
python -m svr.accuracy cases/*.json                      # מבחן דיוק זיהוי (11.1א)
```

## Build ופרסום (לפי כללי Shiluv)
```bash
docker build -t ghcr.io/shiluv-i2r/impact360-sav-runner:latest --build-arg BUILD_TIME="$(date '+%Y-%m-%d %H:%M')" .
docker tag  ghcr.io/shiluv-i2r/impact360-sav-runner:latest ghcr.io/shiluv-i2r/impact360-sav-runner:<version>
docker push ghcr.io/shiluv-i2r/impact360-sav-runner:latest
docker push ghcr.io/shiluv-i2r/impact360-sav-runner:<version>
```
הפריסה ב-QNAP (רצים על ה-NAS, Claude לא ניגש אליו): `docker-compose pull && docker-compose up -d` — עם `docker-compose.yml` שבספריה, אחרי התאמת נתיב ה-volume.

**הרשאות ל-`/data`:** המיכל רץ כמשתמש לא-root (uid 10001). אם תיקיית `./data` ב-NAS שייכת ל-admin/root המיכל לא יצליח לכתוב ויקרוס בהפעלה. פעם אחת, על ה-NAS: `chown -R 10001:10001 ./data` (או `user: "<uid>:<gid>"` ב-compose). בדיקה: `GET /api/health` מחזיר 503 כשאי אפשר לכתוב.

## הגדרות (משתני סביבה)
| משתנה | ברירת מחדל | תיאור |
|---|---|---|
| `DATA_DIR` | `/data` | uploads, projects, library, logs |
| `MAX_UPLOAD_MB` | 1024 | גודל העלאה מרבי |
| `UPLOAD_RETENTION_DAYS` | 14 | מחיקת SAV/שאלון |
| `PROJECT_RETENTION_DAYS` | 180 | מחיקת מצב פרויקט + פלט (אגרגטים בלבד) |
| `WORKERS` | 2 | הרצות במקביל |
| `BASIC_AUTH_USER/PASS` | ריק | אימות אופציונלי (כבוי כברירת מחדל: רשת פנימית) |

## אבטחה ופרטיות
אין קריאות רשת החוצה (גופן ארוז ב-image). דגלי קודים ברמת משיב לא נשלחים לדפדפן — כל התצוגה החיה מחושבת בשרת ומחזירה אחוזים וספירות בלבד. הלוגים לא מכילים ערכי משיבים. ה-image מכיל את המתודולוגיה: הגבל גישה ל-Container Station ולרישום ה-image (ראו סעיף 13 באפיון).
