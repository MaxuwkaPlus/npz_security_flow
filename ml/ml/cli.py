"""Офлайн-команды поверх тех же функций, что и сервис.

Нужны, чтобы смотреть на данные и правила без поднятого HTTP: разбор корпуса,
рекомендация по одной сессии, поиск системных проблем и работа с очередью эксперта.

    python -m ml.cli analyze --source corpus
    python -m ml.cli advice --session EAVT-L1-NO-VERIFICATION-009 --source corpus
    python -m ml.cli mine --source corpus
    python -m ml.cli proposals --status draft
    python -m ml.cli review <id> --approve --expert expert-1
"""

import argparse
import json
import sys

from ml import data, llm, mining, proposals, recommend, skills


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ml", description="ML-часть тренажёра ЭЛОУ-АВТ")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="разбор всех прохождений источника")
    analyze.add_argument("--source", choices=("corpus", "backend"), default="corpus")

    advice = commands.add_parser("advice", help="рекомендация по одному прохождению")
    advice.add_argument("--session", required=True)
    advice.add_argument("--source", choices=("corpus", "backend"), default="backend")
    advice.add_argument("--json", action="store_true", help="печатать JSON целиком")

    mine = commands.add_parser("mine", help="системные проблемы и черновики новых сценариев")
    mine.add_argument("--source", choices=("corpus", "backend"), default="corpus")
    mine.add_argument("--save", action="store_true", help="положить черновики в очередь эксперта")

    queue = commands.add_parser("proposals", help="очередь предложений эксперту")
    queue.add_argument("--status", choices=("draft", "approved", "rejected"))

    review = commands.add_parser("review", help="решение эксперта по предложению")
    review.add_argument("proposal_id")
    review.add_argument("--expert", required=True)
    review.add_argument("--comment")
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")

    args = parser.parse_args(argv)
    handlers = {
        "analyze": _analyze,
        "advice": _advice,
        "mine": _mine,
        "proposals": _proposals,
        "review": _review,
    }
    return handlers[args.command](args)


def _load(source: str) -> list[data.SessionFacts]:
    return data.load_corpus() if source == "corpus" else data.load_backend_sessions()


def _analyze(args: argparse.Namespace) -> int:
    sessions = _load(args.source)
    if not sessions:
        print("Прохождений не найдено.")
        return 1

    profiles = [skills.evaluate(facts) for facts in sessions]
    print(f"Прохождений: {len(profiles)}\n")
    print(f"{'сессия':32} {'ур.':>3}  {'слабое место':32} балл")
    for profile in profiles:
        weak = profile.weak_skill
        name = weak.name if weak else "—"
        score = f"{weak.score:g}" if weak else ""
        print(f"{profile.session_id[:32]:32} {profile.level_no:>3}  {name:32} {score}")

    print("\nСредние баллы по навыкам:")
    for code, score in skills.average_scores(profiles).items():
        print(f"  {code:16} {score:5.1f}")
    print("\nДоля прохождений, где навык слаб:")
    for code, share in skills.weak_share(profiles).items():
        print(f"  {code:16} {share:5.0%}")
    return 0


def _advice(args: argparse.Namespace) -> int:
    sessions = _load(args.source)
    facts = next((item for item in sessions if item.session_id == args.session), None)
    if facts is None:
        print(f"Прохождение не найдено: {args.session}", file=sys.stderr)
        return 1

    profile = skills.evaluate(facts)
    recommendation = recommend.build(facts, profile).to_json()
    text = llm.describe_recommendation(recommendation)

    if args.json:
        print(json.dumps({"recommendation": recommendation, "text": text}, ensure_ascii=False, indent=2))
        return 0

    print(f"{text['title']}\n")
    print(text["summary"], "\n")
    print("Навыки:")
    for skill in profile.skills.values():
        score = "не оценивался" if skill.score is None else f"{skill.score:g}"
        mark = " ←" if skill.is_weak else ""
        print(f"  {skill.name:34} {score:>14}{mark}  — {skill.evidence}")
    if recommendation["also_weak"]:
        print(f"  Прочие слабые места: {', '.join(recommendation['also_weak'])}")
    scenario = recommendation["scenario"]
    print("\nСледующее прохождение:")
    print(
        f"  уровень {scenario['level_no']}, причина «{scenario['disturbance_cause']}», "
        f"ветвь {scenario['target_branch']}"
    )
    print(f"  изменённые параметры: {', '.join(scenario['changed_knobs']) or 'нет'}")
    print(f"  отрабатываемые шаги: {', '.join(scenario['focus_steps'])}")
    print(f"\nИнструктору: {text['instructor_note']}")
    print(f"\nИсточник текста: {text['source']}. Требуется утверждение эксперта.")
    return 0


def _mine(args: argparse.Namespace) -> int:
    findings = mining.mine(_load(args.source))
    if not findings:
        print("Системных проблем не найдено или данных пока недостаточно.")
        return 0

    conn = proposals.connect() if args.save else None
    for finding in findings:
        text = llm.describe_scenario_proposal(finding.to_json())
        print(f"\n[{finding.code}] {text['title']}")
        print(f"  {finding.summary}")
        print(f"  Назначение: {text['purpose']}")
        print(
            f"  Сценарий: уровень {finding.scenario['level_no']}, "
            f"шаги {', '.join(finding.scenario['focus_steps'])}"
        )
        if conn is not None:
            proposal = proposals.save_draft(
                conn,
                kind=proposals.KIND_NEW_SCENARIO,
                dedup_key=finding.key,
                title=text["title"],
                payload={"finding": finding.to_json(), "text": text},
                evidence=[finding.summary],
            )
            print(f"  Черновик в очереди эксперта: {proposal.id}")
    if conn is not None:
        conn.close()
    return 0


def _proposals(args: argparse.Namespace) -> int:
    conn = proposals.connect()
    items = proposals.list_proposals(conn, status=args.status)
    conn.close()
    if not items:
        print("Очередь пуста.")
        return 0
    for item in items:
        reviewer = f" ({item.reviewed_by})" if item.reviewed_by else ""
        print(f"{item.id}  {item.status:9}{reviewer}  {item.kind:15} {item.title}")
    return 0


def _review(args: argparse.Namespace) -> int:
    conn = proposals.connect()
    try:
        result = proposals.review(
            conn,
            args.proposal_id,
            status=proposals.STATUS_APPROVED if args.approve else proposals.STATUS_REJECTED,
            expert_id=args.expert,
            comment=args.comment,
        )
    except (proposals.ProposalNotFound, proposals.ProposalAlreadyReviewed) as error:
        print(f"Решение не принято: {error}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"{result.id}: {result.status} ({result.reviewed_by})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
