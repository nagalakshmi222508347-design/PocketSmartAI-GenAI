"""PocketSmart AI - FastAPI backend. Run: python main.py"""
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import auth
import db
import gemini_utils as ai

BASE = Path(__file__).parent
app = FastAPI(title="PocketSmart AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))


def page(request, name, user=None, **ctx):
    return templates.TemplateResponse(request, name, {"user": user, **ctx})


@app.on_event("startup")
def startup():
    db.init_db()


@app.exception_handler(auth.NotAuthenticated)
def not_authenticated(request: Request, exc):
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------- public pages
@app.get("/")
def index(request: Request, user=Depends(auth.get_optional_user)):
    return page(request, "index.html", user)


@app.get("/register")
def register_page(request: Request):
    return page(request, "register.html")


@app.post("/register")
def register(request: Request, username: str = Form(...), email: str = Form(""), password: str = Form(...)):
    if len(password) < 6:
        return page(request, "register.html", error="Password must be at least 6 characters.")
    if not db.create_user(username.strip(), email, auth.hash_password(password)):
        return page(request, "register.html", error="Username already taken.")
    return RedirectResponse("/login?registered=1", status_code=303)


@app.get("/login")
def login_page(request: Request, registered: int = 0):
    return page(request, "login.html", msg="Account created! Please log in." if registered else None)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = auth.authenticate(username.strip(), password)
    if not user:
        return page(request, "login.html", error="Invalid username or password.")
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("access_token", auth.create_token(user["username"]), httponly=True,
                    max_age=auth.TOKEN_HOURS * 3600)
    return resp


@app.post("/token")
def token(form: OAuth2PasswordRequestForm = Depends()):
    """JWT for API clients (e.g. Swagger /docs)."""
    user = auth.authenticate(form.username, form.password)
    if not user:
        return JSONResponse({"detail": "Incorrect username or password"}, status_code=401)
    return {"access_token": auth.create_token(user["username"]), "token_type": "bearer"}


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


# ---------------------------------------------------------------- session APIs
@app.get("/session-info")
def session_info(user=Depends(auth.get_current_user)):
    return {"user_id": user["id"], "username": user["username"], "logged_in": True}


@app.get("/session-data")
def session_data(user=Depends(auth.get_current_user)):
    rows = db.list_history(user["id"], 100)
    by_cat = {}
    for r in rows:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    return {"username": user["username"], "total_queries": len(rows), "by_category": by_cat}


# ---------------------------------------------------------------- dashboard
@app.get("/dashboard")
def dashboard(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "dashboard.html", user, recent=db.list_history(user["id"], 5))


# ---------------------------------------------------------------- planners
def show_result(request, user, category, budget, inputs, data):
    hid = db.save_history(user["id"], category, budget, inputs, data)
    return page(request, "results.html", user, category=category, data=data, hid=hid)


@app.get("/home-planner")
def home_planner(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "home_planner.html", user)


@app.post("/generate-home")
def generate_home(request: Request, budget: float = Form(...), style: str = Form("Modern"),
                  room: list[str] = Form(...), lights: list[int] = Form(...),
                  fans: list[int] = Form(...), tables: list[int] = Form(...),
                  user=Depends(auth.get_current_user)):
    if budget < 1000:
        return page(request, "home_planner.html", user, error="Minimum budget is ₹1,000.")
    rooms = [{"room": r, "lights": l, "fans": f, "tables": t} for r, l, f, t in zip(room, lights, fans, tables)]
    data = ai.home_recommendations(budget, style, rooms)
    return show_result(request, user, "Home Interior", budget, {"style": style, "rooms": rooms}, data)


@app.get("/party-planner")
def party_planner(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "party_planner.html", user)


@app.post("/generate-party")
def generate_party(request: Request, budget: float = Form(...), guests: int = Form(...),
                   event_type: str = Form("Birthday"), venue: str = Form("Home"), city: str = Form("Chennai"),
                   user=Depends(auth.get_current_user)):
    if budget < 1000 or guests < 1:
        return page(request, "party_planner.html", user, error="Enter a budget ≥ ₹1,000 and at least 1 guest.")
    data = ai.party_recommendations(budget, guests, event_type, venue, city)
    inputs = {"event_type": event_type, "guests": guests, "venue": venue, "city": city}
    return show_result(request, user, "Party", budget, inputs, data)


@app.get("/jewelry-planner")
def jewelry_planner(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "jewelry_planner.html", user)


@app.post("/generate-jewelry")
async def generate_jewelry(request: Request, budget: float = Form(...), occasion: str = Form(...),
                           style: str = Form("Traditional"), outfit: UploadFile | None = File(None),
                           user=Depends(auth.get_current_user)):
    if budget < 500:
        return page(request, "jewelry_planner.html", user, error="Minimum budget is ₹500.")
    image = None
    if outfit and outfit.filename:
        raw = await outfit.read()
        if raw and len(raw) <= 5_000_000 and (outfit.content_type or "").startswith("image/"):
            image = (raw, outfit.content_type)
    data = ai.jewelry_recommendations(budget, occasion, style, image)
    inputs = {"occasion": occasion, "style": style, "image_uploaded": bool(image)}
    return show_result(request, user, "Jewelry", budget, inputs, data)


# ---------------------------------------------------------------- history
@app.get("/history")
def history(request: Request, user=Depends(auth.get_current_user)):
    return page(request, "history.html", user, rows=db.list_history(user["id"]))


@app.get("/recommendations-details/{hid}")
def recommendation_details(request: Request, hid: int, user=Depends(auth.get_current_user)):
    row = db.get_history(hid, user["id"])
    if not row:
        return RedirectResponse("/history", status_code=303)
    return page(request, "results.html", user, category=row["category"], data=json.loads(row["result"]), hid=hid)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
