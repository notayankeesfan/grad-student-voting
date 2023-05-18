"""
CLI interface to add/remove elections and votes.
"""
import argparse

import sqlalchemy
from sqlalchemy.orm import Session

from .models import *

parser = argparse.ArgumentParser(prog="vote CLI")
subparsers = parser.add_subparsers(
    help="sub-command help", required=True, dest="subparser_category"
)

election_parser = subparsers.add_parser("election", help="election help")
election_subparsers = election_parser.add_subparsers(
    required=True, dest="subparser_command"
)
add_election_parser = election_subparsers.add_parser("add")
add_election_parser.add_argument("name")
add_election_parser.add_argument("open_datetime", type=datetime.datetime.fromisoformat)
add_election_parser.add_argument("close_datetime", type=datetime.datetime.fromisoformat)
open_time_election_parser = election_subparsers.add_parser("open_time")
open_time_election_parser.add_argument("id", type=int)
open_time_election_parser.add_argument(
    "open_datetime", type=datetime.datetime.fromisoformat
)
close_time_election_parser = election_subparsers.add_parser("close_time")
close_time_election_parser.add_argument("id", type=int)
close_time_election_parser.add_argument(
    "close_datetime", type=datetime.datetime.fromisoformat
)
toggle_election_parser = election_subparsers.add_parser("toggle")
toggle_election_parser.add_argument("id", type=int)
remove_election_parser = election_subparsers.add_parser("remove")
remove_election_parser.add_argument("id", type=int)
list_election_parser = election_subparsers.add_parser("list")

question_parser = subparsers.add_parser("question", help="question help")
question_subparsers = question_parser.add_subparsers(
    required=True, dest="subparser_command"
)
add_question_parser = question_subparsers.add_parser("add")
add_question_parser.add_argument("election_id")
add_question_parser.add_argument("name")
add_question_parser.add_argument("options", nargs="+")
remove_question_parser = question_subparsers.add_parser("remove")
remove_question_parser.add_argument("id", type=int)

args = parser.parse_args()

# Setup database
db_engine = sqlalchemy.create_engine("sqlite:////var/lib/vote-daemon/elections.db")
OrmBase.metadata.create_all(db_engine)

if args.subparser_category == "election":
    if args.subparser_command == "list":
        with Session(db_engine) as session:
            stmt = sqlalchemy.select(Election)
            for election in session.scalars(stmt):
                print(
                    f"{election.name}\n\tid: {election.id}\n\tvisible: {election.visible}\n\topen: {election.open_timestamp}\n\tclose: {election.close_timestamp}"
                )
                for question in election.questions:
                    print(f"\tquestion: {question.name} (id: {question.id})")
                    for option in question.options:
                        print(f"\t\t- {option.name}")
    elif args.subparser_command == "add":
        with Session(db_engine) as session:
            election = Election(
                name=args.name,
                visible=False,
                open_timestamp=args.open_datetime,
                close_timestamp=args.close_datetime,
            )
            session.add(election)
            session.commit()
    elif args.subparser_command == "toggle":
        with Session(db_engine) as session:
            stmt = sqlalchemy.select(Election).where(Election.id == args.id)
            election = session.scalar(stmt)
            if election is None:
                raise ValueError("Invalid election ID")
            election.visible = not election.visible
            session.commit()
    elif args.subparser_command == "open_time":
        with Session(db_engine) as session:
            stmt = sqlalchemy.select(Election).where(Election.id == args.id)
            election = session.scalar(stmt)
            if election is None:
                raise ValueError("Invalid election ID")
            election.open_timestamp = args.open_datetime
            session.commit()
    elif args.subparser_command == "close_time":
        with Session(db_engine) as session:
            stmt = sqlalchemy.select(Election).where(Election.id == args.id)
            election = session.scalar(stmt)
            if election is None:
                raise ValueError("Invalid election ID")
            election.close_timestamp = args.close_datetime
            session.commit()
    elif args.subparser_command == "remove":
        with Session(db_engine) as session:
            stmt = sqlalchemy.select(Election).where(Election.id == args.id)
            election = session.scalar(stmt)
            if election is None:
                raise ValueError("Invalid election ID")
            session.delete(election)
            session.commit()
elif args.subparser_category == "question":
    if args.subparser_command == "add":
        with Session(db_engine) as session:
            question = Question(
                name=args.name,
                election_id=args.election_id,
            )
            for option in args.options:
                question.options.append(QuestionOption(name=option))
            session.add(question)
            session.commit()
    elif args.subparser_comand == "remove":
        with Session(db_engine) as session:
            stmt = sqlalchemy.select(Question).where(Question.id == args.id)
            question = session.scalar(stmt)
            if question is None:
                raise ValueError("Invalid election ID")
            session.delete(question)
            session.commit()
