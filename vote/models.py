from typing import List
import datetime
import uuid

from sqlalchemy import ForeignKey
from sqlalchemy import String, DateTime, Boolean
import sqlalchemy.orm
from sqlalchemy.orm import Mapped, mapped_column, relationship


class OrmBase(sqlalchemy.orm.DeclarativeBase):
    pass


# Store votes separate from voters
class Vote(OrmBase):
    """Stores the select question option"""

    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(
        primary_key=True, default=lambda: uuid.uuid4().int >> (128 - 32)
    )
    question_option: Mapped[int] = mapped_column(ForeignKey("question_options.id"))


class Voter(OrmBase):
    """Stores who has voted for each election, but not their selections"""

    __tablename__ = "voters"

    kerberos: Mapped[str] = mapped_column(String, primary_key=True)
    election_id: Mapped[int] = mapped_column(
        ForeignKey("elections.id"), primary_key=True
    )


class VoterEligibility(OrmBase):
    """Stores if the given kerberos is a valid voter (e.g. a grad student)"""

    __tablename__ = "cached_eligible"

    kerberos: Mapped[str] = mapped_column(String, primary_key=True)


class BrowserSession(OrmBase):
    """Stores the cookies that track sessions"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    kerberos: Mapped[str] = mapped_column(String)
    cookie: Mapped[str] = mapped_column(String, index=True)
    expiration: Mapped[datetime.datetime] = mapped_column(DateTime)


class LoginToken(OrmBase):
    __tablename__ = "login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    kerberos: Mapped[str] = mapped_column(String)
    token: Mapped[str] = mapped_column(String)
    expiration: Mapped[datetime.datetime] = mapped_column(DateTime)


class Election(OrmBase):
    """Stores the top level election information"""

    __tablename__ = "elections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    visible: Mapped[bool] = mapped_column(Boolean)
    open_timestamp: Mapped[datetime.datetime] = mapped_column(DateTime)
    close_timestamp: Mapped[datetime.datetime] = mapped_column(DateTime)

    questions: Mapped[List["Question"]] = relationship(
        back_populates="election", cascade="all, delete"
    )


class Question(OrmBase):
    """Stores ballot questions for an election"""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    election_id: Mapped[int] = mapped_column(ForeignKey("elections.id"))

    election: Mapped["Election"] = relationship(back_populates="questions")

    options: Mapped[List["QuestionOption"]] = relationship(
        back_populates="question", cascade="all, delete"
    )


class QuestionOption(OrmBase):
    """Stores options for these ballot questions"""

    __tablename__ = "question_options"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))

    question: Mapped["Question"] = relationship(back_populates="options")
