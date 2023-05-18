import base64
import email
import email.headerregistry
import email.message
import hmac
import json
import secrets
import smtplib
import ssl
from typing import Dict, Optional, Tuple

import jinja2
import requests
import sqlalchemy
import sqlalchemy.exc
from fastapi import (
    BackgroundTasks,
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseSettings

from .models import *

# Setup database
db_engine = sqlalchemy.create_engine(
    "sqlite:////var/lib/vote-daemon/elections.db", echo=False
)
OrmBase.metadata.create_all(db_engine)

# Setup website templating
# Use this isntead of Jinja2Templates with fastapi because we need to send templated emails
templates = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    autoescape=jinja2.select_autoescape(["html"]),
)


class Settings(BaseSettings):
    csrf_key: str = ""
    base_url: str = "http://localhost:9000"
    smtp_username: str = ""
    smtp_password: str = ""

    class Config:
        secrets_dir = "/var/lib/vote-daemon/secrets"


settings = Settings()


def get_login_status(cookie: Optional[str], session: sqlalchemy.orm.Session) -> Dict:
    now = datetime.datetime.now()
    stmt = (
        sqlalchemy.select(BrowserSession)
        .where(BrowserSession.cookie == cookie)
        .where(BrowserSession.expiration > now)
    )
    browser_session = session.scalar(stmt)
    if browser_session is None:
        return {"logged_in": False}
    # Bump the expiration
    browser_session.expiration = now + datetime.timedelta(hours=1)
    session.commit()
    return {"logged_in": True, "kerberos": browser_session.kerberos}


def generate_csrf() -> Tuple[str, str]:
    # Generate random token
    token = secrets.token_bytes(32)
    digest = hmac.digest(settings.csrf_key.encode("utf-8"), token, "sha256")

    return (
        base64.b64encode(token).decode("utf-8"),
        base64.b64encode(digest).decode("utf-8"),
    )


def validate_csrf(token_str: str, signed_str: str) -> bool:
    # Compute digest of the token
    try:
        token = base64.b64decode(token_str.encode("utf-8"))
        signed = base64.b64decode(signed_str.encode("utf-8"))

        digest = hmac.digest(settings.csrf_key.encode("utf-8"), token, "sha256")
        return hmac.compare_digest(signed, digest)
    except Exception:
        return False


def is_grad_student(kerberos: str) -> bool:
    """Checks that the given kerberos is a grad student by checking tlepeopledir"""
    with sqlalchemy.orm.Session(db_engine) as session:
        # First, check the cache
        stmt = sqlalchemy.select(VoterEligibility).where(
            VoterEligibility.kerberos == kerberos
        )
        if session.scalar(stmt) is not None:
            return True
        # If not, request from the directory
        r = requests.get(
            f"https://tlepeopledir.mit.edu/q/{kerberos}", params={"_format": "json"}
        )
        lookup = r.json()
        if "result" in lookup:
            for result in lookup["result"]:
                if (
                    "email_id" in result
                    and result["email_id"] == kerberos
                    and "email_domain" in result
                    and result["email_domain"] == "mit.edu"
                    and "student_year" in result
                    and result["student_year"] == "G"
                ):
                    session.add(VoterEligibility(kerberos=kerberos))
                    session.commit()
                    return True
    return False


def send_login_email(kerberos: str):
    now = datetime.datetime.now()
    # Check for grad student status
    if not is_grad_student(kerberos):
        return
    with sqlalchemy.orm.Session(db_engine) as session:
        # Check that an existing token does not exist.
        token = LoginToken(
            kerberos=kerberos,
            token=secrets.token_urlsafe(64),
            expiration=now + datetime.timedelta(minutes=10),
        )
        session.add(token)

        msg = email.message.EmailMessage()
        msg["Subject"] = "Voting login link"
        msg["From"] = email.headerregistry.Address(
            display_name="Grad voting system (uenotformit)",
            addr_spec="uenotformit-contributors@mit.edu",
        )
        msg["To"] = email.headerregistry.Address(addr_spec=f"{kerberos}@mit.edu")
        msg.set_content(
            templates.get_template("token_email.txt").render(
                {"url": f"{settings.base_url}/login/{token.token}"}
            )
        )

        context = ssl.create_default_context()
        with smtplib.SMTP("outgoing.mit.edu", port=587) as s:
            s.starttls(context=context)
            s.login(settings.smtp_username, settings.smtp_password)
            s.send_message(msg)

        session.commit()


app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def root(vote_session: Optional[str] = Cookie(default=None)):
    now = datetime.datetime.now()
    with sqlalchemy.orm.Session(db_engine) as session:
        template_vals: Dict = {
            **{"open_elections": [], "closed_elections": []},
            **get_login_status(vote_session, session),
        }
        print(template_vals)

        stmt = sqlalchemy.select(Election).where(Election.visible == True)
        elections = session.scalars(stmt)
        for election in elections:
            if template_vals["logged_in"] == False:
                has_voted = False
            else:
                vote_stmt = (
                    sqlalchemy.select(Voter)
                    .where(Voter.election_id == election.id)
                    .where(Voter.kerberos == template_vals["kerberos"])
                )
                has_voted = session.scalar(vote_stmt) is not None
            election_dict = {
                "id": election.id,
                "name": election.name,
                "close": election.close_timestamp,
                "has_voted": has_voted,
                "questions": [
                    {
                        "name": question.name,
                        "options": [
                            {
                                "name": option.name,
                                "votes": session.query(Vote)
                                .filter(Vote.question_option == option.id)
                                .count(),
                            }
                            for option in question.options
                        ],
                    }
                    for question in election.questions
                ],
            }
            if len(election_dict["questions"]) == 0:
                election_dict["total_votes"] = 0
            else:
                election_dict["total_votes"] = sum(
                    o["votes"] for o in election_dict["questions"][0]["options"]
                )

            if election.close_timestamp < now:
                template_vals["closed_elections"].append(election_dict)
            elif election.open_timestamp < now:
                # Compute votes for each option
                template_vals["open_elections"].append(election_dict)

        return templates.get_template("main.html").render(template_vals)


@app.get("/vote/{election_id}", response_class=HTMLResponse)
def render_vote_page(
    response: Response,
    election_id: int,
    vote_session: Optional[str] = Cookie(default=None),
):
    now = datetime.datetime.now()
    csrf = generate_csrf()
    response.set_cookie(
        key="vote_csrf", value=csrf[1], secure=True, httponly=True, samesite="strict"
    )
    with sqlalchemy.orm.Session(db_engine) as session:
        template_dict = {**{"csrf": csrf[0]}, **get_login_status(vote_session, session)}
        if template_dict["logged_in"] == False:
            template_dict["alert"] = "You must be logged in to vote!"
            template_dict["alert_type"] = "danger"
            return templates.get_template("vote.html").render(template_dict)
        # Check if the election exists
        stmt = (
            sqlalchemy.select(Election)
            .where(Election.id == election_id)
            .where(Election.visible == True)
            .where(Election.open_timestamp < now)
        )
        election = session.scalar(stmt)
        if election is None:
            template_dict["alert"] = "Invalid election ID"
            template_dict["alert_type"] = "danger"
            return templates.get_template("vote.html").render(template_dict)
        if election.close_timestamp < now:
            template_dict["alert"] = "This election has closed"
            template_dict["alert_type"] = "info"
            return templates.get_template("vote.html").render(template_dict)

        # Check if the voter has already voted
        stmt = (
            sqlalchemy.select(Voter)
            .where(Voter.election_id == election_id)
            .where(Voter.kerberos == template_dict["kerberos"])
        )
        voter = session.scalar(stmt)
        if voter is not None:
            template_dict["alert"] = "You have successfully voted."
            template_dict["alert_type"] = "success"
            return templates.get_template("vote.html").render(template_dict)

        # Otherwise, return the questions
        template_dict["election"] = {
            "id": election.id,
            "name": election.name,
            "close": election.close_timestamp,
            "questions": [
                {
                    "id": question.id,
                    "name": question.name,
                    "options": [
                        {"name": option.name, "id": option.id}
                        for option in question.options
                    ],
                }
                for question in election.questions
            ],
        }
    return templates.get_template("vote.html").render(template_dict)


async def process_vote_body(request: Request) -> Dict[str, str]:
    form = await request.form()
    result: Dict[str, str] = {}
    for k, v in form.items():
        # Skip uploaded files, if present
        if isinstance(v, str):
            result[k] = v
    return result


@app.post("/vote/{election_id}", response_class=HTMLResponse)
async def vote(
    election_id: int,
    response: Response,
    background_tasks: BackgroundTasks,
    votes: Dict[str, str] = Depends(process_vote_body),
    csrf: str = Form(),
    vote_session: Optional[str] = Cookie(default=None),
    vote_csrf: str = Cookie(),
):
    # Redirect back to the GET page in all instances
    response = RedirectResponse(url=f"/vote/{election_id}", status_code=303)
    now = datetime.datetime.now()
    if not validate_csrf(csrf, vote_csrf):
        return HTMLResponse(status_code=401)

    try:
        with sqlalchemy.orm.Session(db_engine) as session:
            # Check login status
            login_status = get_login_status(vote_session, session)
            if login_status["logged_in"] == False:
                return response
            # Check that the election exists (and is open)
            stmt = (
                sqlalchemy.select(Election)
                .where(Election.id == election_id)
                .where(Election.visible == True)
                .where(Election.open_timestamp < now)
            )
            election = session.scalar(stmt)
            if election is None or election.close_timestamp < now:
                return response
            session.rollback()
            with session.begin():
                # This add will fail if the voter has already voted, auto-aborting
                voter = Voter(
                    kerberos=login_status["kerberos"], election_id=election_id
                )
                session.add(voter)

                submitted_questions = []
                for k, v in votes.items():
                    if k.startswith("question-"):
                        vote_question = int(k[9:])
                        vote = int(v)
                        stmt = sqlalchemy.select(QuestionOption).where(
                            QuestionOption.id == vote
                        )
                        question_option = session.scalar(stmt)
                        # Validate that the vote is actually for this question and this election
                        if question_option is None:
                            raise RuntimeError("Invalid question option for vote")
                        if question_option.question.id != vote_question:
                            raise RuntimeError("Invalid question for this option")
                        if question_option.question.election_id != election_id:
                            raise RuntimeError("Invalid option for this election")

                        submitted_questions.append(vote_question)
                        session.add(Vote(question_option=vote))
                election_questions = session.scalars(
                    sqlalchemy.select(Question).where(
                        Question.election_id == election_id
                    )
                ).all()
                if set(submitted_questions) != {q.id for q in election_questions}:
                    raise RuntimeError("Did not submit a complete ballot!")
    except sqlalchemy.exc.SQLAlchemyError:
        pass
    except RuntimeError:
        pass
    # Refresh page
    return response


@app.get("/request_login", response_class=HTMLResponse)
def render_login_page(
    response: Response,
    warning: Optional[str] = None,
    vote_session: Optional[str] = Cookie(default=None),
):
    csrf = generate_csrf()
    with sqlalchemy.orm.Session(db_engine) as session:
        template_dict = {**{"csrf": csrf[0]}, **get_login_status(vote_session, session)}
        if warning is not None:
            template_dict["alert_type"] = "warning"
            template_dict["alert"] = warning
        response.set_cookie(
            key="vote_csrf",
            value=csrf[1],
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return templates.get_template("request_login.html").render(template_dict)


@app.post("/request_login", response_class=HTMLResponse)
def check_response(
    response: Response,
    background_tasks: BackgroundTasks,
    csrf: str = Form(),
    kerberos: str = Form(),
    vote_csrf: str = Cookie(),
):
    now = datetime.datetime.now()
    if not validate_csrf(csrf, vote_csrf):
        return HTMLResponse(status_code=401)
    # Refresh page
    new_csrf = generate_csrf()
    template_dict = {"csrf": new_csrf[0]}
    # Check that there isn't already a token
    with sqlalchemy.orm.Session(db_engine) as session:
        stmt = (
            sqlalchemy.select(LoginToken)
            .where(LoginToken.kerberos == kerberos)
            .where(LoginToken.expiration > now)
        )
        tokens = session.scalars(stmt).all()
        if len(tokens) == 0:
            # Create new token and send an email using the background task
            background_tasks.add_task(send_login_email, kerberos)
            template_dict["alert_type"] = "info"
            template_dict[
                "alert"
            ] = "Check your email! An email should arrive if you are a graduate student."
        else:
            template_dict["alert_type"] = "warning"
            template_dict[
                "alert"
            ] = "A login token was already generated! You can only request one login token every ten minutes"

    response.set_cookie(
        key="vote_csrf",
        value=new_csrf[1],
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return templates.get_template("request_login.html").render(template_dict)


@app.get("/login/{token}")
def login_with_token(response: Response, token: str):
    now = datetime.datetime.now()
    response = RedirectResponse(url="/")
    with sqlalchemy.orm.Session(db_engine) as session:
        # Check the token
        stmt = (
            sqlalchemy.select(LoginToken)
            .where(LoginToken.token == token)
            .where(LoginToken.expiration > now)
        )
        login_token = session.scalar(stmt)
        if login_token is None:
            return RedirectResponse(
                url="/request_login?warning=Invalid%20login%20token%2C%20it%20may%20have%20expired."
            )
        # Generate a login session
        browser_session = BrowserSession(
            kerberos=login_token.kerberos,
            cookie=secrets.token_urlsafe(64),
            expiration=now + datetime.timedelta(hours=1),
        )
        session.add(browser_session)
        # Expire the login token
        login_token.expiration = datetime.datetime(1970, 1, 1, 0, 0, 0)
        session.commit()
        response.set_cookie(
            key="vote_session",
            value=browser_session.cookie,
            secure=True,
            httponly=True,
            samesite="strict",
        )
    return response


@app.get("/logout")
def logout_remove_session(vote_session: Optional[str] = Cookie(default=None)):
    if vote_session is not None:
        with sqlalchemy.orm.Session(db_engine) as session:
            stmt = sqlalchemy.select(BrowserSession).where(
                BrowserSession.cookie == vote_session
            )
            browser_sessions = session.scalars(stmt).all()
            for bs in browser_sessions:
                session.delete(bs)
            session.commit()
    return RedirectResponse(url="/")
