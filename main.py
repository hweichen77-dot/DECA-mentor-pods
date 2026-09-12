"""Sort DECA mentees into mentor pods for written events.

Reads the merged Google Forms export that holds both mentor and mentee
responses, groups mentees who signed up for the same written event, keeps
declared teammates together, and hands every pod a mentor who has been in DECA
at least as long as the most experienced mentee in that pod.
"""

from pathlib import Path
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict, deque
from itertools import combinations, permutations

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_CSV = SCRIPT_DIR / "MentorAndMenteeResponses.csv"
OUTPUT_XLSX = SCRIPT_DIR / "MentorPodSorting.xlsx"

SOFT_SIZE = 6
HARD_SIZE = 7

PLACEHOLDER_ANSWERS = {"", "n/a", "na", "n a", "no", "none", "nan", "-", "n\\a"}


def normalize_email(value):
    """Lowercase an email and undo the ways people dodge typing an @ sign."""
    if not isinstance(value, str):
        return ""
    cleaned = value.strip().lower().replace(" ", "")
    return cleaned.replace("(at)", "@").replace("[at]", "@")


def normalize_text(value):
    """Collapse runs of whitespace and lowercase, so two spellings of the same
    answer compare equal."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def name_fingerprint(value):
    """Reduce a written name to its sorted word parts.

    Students type teammates as "Litian Gu" while the form's own columns store
    first and last name separately, and a few people reverse the order. Sorting
    the word parts means every spelling of one person lands on the same key.
    """
    parts = re.findall(r"[a-z']+", normalize_text(value))
    return tuple(sorted(parts))


def event_abbreviation(value):
    """Pull the code out of an event label, so "Innovation Plan (EIP)" becomes
    EIP. Falls back to the stripped label when there are no parentheses."""
    if not isinstance(value, str):
        return ""
    inside_parentheses = re.search(r"\(([^)]+)\)", value)
    if inside_parentheses:
        code = re.sub(r"[^A-Za-z0-9]", "", inside_parentheses.group(1)).upper()
        if code:
            return code
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def parse_years_in_deca(value):
    """Turn an answer like "3rd Year" into the number 3. Anything without a
    digit in it, such as the one stray "op" response, comes back as NaN."""
    if pd.isna(value):
        return float("nan")
    digits = re.search(r"\d+", str(value))
    return float(digits.group()) if digits else float("nan")


def squash_header(header):
    """Strip a column header down to bare letters and digits for comparison."""
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def find_column(columns, *fragments, default=None):
    """Return the first column whose lowercase header contains every fragment."""
    for column in columns:
        lowered = str(column).lower()
        if all(fragment in lowered for fragment in fragments):
            return column
    return default


def find_mentor_flag_column(columns):
    """Locate the "Are you a Mentor?" question.

    This one needs an exact match rather than a keyword sweep. The form also
    asks people to "Select Roleplay Category", and a loose search for the word
    role picks that up first, which quietly turns every real mentor into a
    mentee.
    """
    for column in columns:
        if squash_header(column) == "areyouamentor":
            return column
    for column in columns:
        if "are you a mentor" in str(column).lower():
            return column
    raise KeyError("The form export has no 'Are you a Mentor?' column.")


def find_written_event_columns(columns, category_column):
    """Collect the five branch columns that hold the actual written event pick.

    The form asks the same "Select Written" question once per event category,
    so pandas renames the duplicates to Select Written.1, .2 and .3, and the
    project management branch carries an approval note in its header. Reading
    only the plain one leaves roughly two thirds of the responses blank.
    """
    found = []
    for column in columns:
        if column == category_column:
            continue
        lowered = str(column).lower()
        if lowered.startswith("select written") and "category" not in lowered:
            found.append(column)
    if not found:
        raise KeyError("The form export has no 'Select Written' branch columns.")
    return found


def map_categories_to_branch_columns(frame, category_column, written_columns):
    """Work out which branch column belongs to which event category.

    Rather than hardcoding five long category names that could be reworded next
    season, this reads where the answers actually landed and keeps the pairing
    that the responses support most strongly.
    """
    strongest = {}
    for column in written_columns:
        answered = frame.loc[frame[column].notna(), category_column].dropna()
        if answered.empty:
            continue
        counts = answered.value_counts()
        category, hits = counts.index[0], int(counts.iloc[0])
        if category not in strongest or hits > strongest[category][1]:
            strongest[category] = (column, hits)
    return {category: column for category, (column, _) in strongest.items()}


def resolve_written_event(row, category_column, written_columns, category_to_column):
    """Read one person's written event out of whichever branch column holds it.

    The category answer says which branch the student went down, so that column
    wins. A handful of people changed categories mid form and left a leftover
    answer behind, and the category is the honest tiebreaker there.
    """
    preferred = category_to_column.get(row[category_column])
    if preferred is not None:
        value = row.get(preferred)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for column in written_columns:
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def find_written_partner_columns(columns, category_column):
    """Find the teammate name and email questions that belong to the written
    event, not the roleplay one.

    Both halves of the form ask about partners in almost the same words. The
    written event questions are the ones that come after the written event
    category, so position settles it.
    """
    columns = list(columns)
    start = columns.index(category_column)
    tail = columns[start:]
    name_column = find_column(tail, "partner", "full team") or find_column(tail, "partner", "name")
    email_column = find_column(tail, "partner", "email")
    return name_column, email_column


def split_partner_emails(value):
    """Split a teammate email answer on commas, semicolons, newlines or plain
    spaces, and drop anything that is not an address."""
    if not isinstance(value, str):
        return []
    pieces = re.split(r"[,;\s]+", value)
    return [address for address in (normalize_email(piece) for piece in pieces) if "@" in address]


def split_partner_names(value):
    """Split a teammate name answer into fingerprints, ignoring the many ways
    people write "no partner".

    The form asks for commas, and plenty of people use "and" or an ampersand
    instead, so both count as separators.
    """
    if not isinstance(value, str):
        return []
    fingerprints = []
    for piece in re.split(r"[,;\n]+|\s+and\s+|\s*&\s*", value):
        cleaned = normalize_text(piece)
        if not cleaned or cleaned in PLACEHOLDER_ANSWERS:
            continue
        fingerprint = name_fingerprint(cleaned)
        if len(fingerprint) >= 2:
            fingerprints.append(fingerprint)
    return fingerprints


def build_teams(mentees, everyone):
    """Join mentees into teams using the teammates they named.

    A link only counts when both people picked the same written event, so a
    shared roleplay partner never drags someone into the wrong pod. Teams come
    back sorted largest first, and anything longer than a full pod gets cut into
    pod sized pieces.

    Names are looked up across every response rather than only the mentees, so
    the three lists that come back can say what actually happened to a teammate
    who did not make it into the team. One holds pairs who picked different
    written events, one holds teammates who are mentors and therefore coach
    rather than compete, and one holds names and addresses that match nobody at
    all, which is usually a typo or somebody who never filled the form in.
    """
    index_by_email = {}
    index_by_name = {}
    for index, row in everyone.iterrows():
        if row["mentee_email"]:
            index_by_email.setdefault(row["mentee_email"], index)
        if len(row["mentee_name_key"]) >= 2:
            index_by_name.setdefault(row["mentee_name_key"], index)
    for index, row in everyone.iterrows():
        if len(row["email_name_key"]) >= 2:
            index_by_name.setdefault(row["email_name_key"], index)

    in_a_pod = set(mentees.index)
    neighbours = defaultdict(set)
    conflicts = set()
    mentor_teammates = []
    missing = []

    for index, row in mentees.iterrows():
        event = row["event_code"]
        claims = []
        for address in row["partner_emails"]:
            found = index_by_email.get(address)
            if found is None:
                missing.append((index, address))
            else:
                claims.append(found)
        for key in row["partner_names"]:
            found = index_by_name.get(key)
            if found is None:
                if key != row["mentee_name_key"] and key != row["email_name_key"]:
                    missing.append((index, " ".join(key)))
            else:
                claims.append(found)

        for other in claims:
            if other == index:
                continue
            if other not in in_a_pod:
                mentor_teammates.append((index, other))
                continue
            if mentees.at[other, "event_code"] != event:
                conflicts.add((min(index, other), max(index, other)))
                continue
            neighbours[index].add(other)
            neighbours[other].add(index)

    teams = []
    seen = set()
    for index in mentees.index:
        if index in seen:
            continue
        team = []
        queue = deque([index])
        seen.add(index)
        while queue:
            current = queue.popleft()
            team.append(current)
            for other in neighbours[current]:
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        team.sort()
        for start in range(0, len(team), HARD_SIZE):
            teams.append(team[start:start + HARD_SIZE])

    teams.sort(key=lambda team: (-len(team), team[0]))
    return teams, sorted(conflicts), sorted(set(mentor_teammates)), missing


def pack_teams_into_pods(teams, hard_size=HARD_SIZE, group_of=None):
    """Spread teams across pods so the pods come out as evenly sized as the
    event allows, without splitting a team.

    The pod count is decided up front from how many mentees the event has, every
    pod aims at an equal share of them, and whole teams move between pods until
    the sizes stop getting closer together. Filling pods to the cap first and
    patching afterwards runs out of movable people and strands pods of two and
    three, so the even target comes first.

    When a pod has to carry more than one written event, pass group_of to say
    which event each team belongs to. Teams are then laid down event by event
    rather than scattered, which keeps the mixing down to the seams.
    """
    people = sum(len(team) for team in teams)
    if people == 0:
        return []

    pod_count = max(1, -(-people // hard_size))
    ideal_size = people / pod_count
    pods = [[] for _ in range(pod_count)]

    if group_of is None:
        for team in sorted(teams, key=lambda team: (-len(team), team[0])):
            smallest = min(range(pod_count), key=lambda slot: (sum(len(t) for t in pods[slot]), slot))
            pods[smallest].append(team)
    else:
        targets = [people // pod_count + (1 if slot < people % pod_count else 0)
                   for slot in range(pod_count)]
        slot = 0
        for team in sorted(teams, key=lambda team: (group_of(team), -len(team), team[0])):
            while slot < pod_count - 1 and sum(len(t) for t in pods[slot]) >= targets[slot]:
                slot += 1
            pods[slot].append(team)

    def spread_cost(sizes):
        return sum((size - ideal_size) ** 2 for size in sizes)

    while True:
        sizes = [sum(len(team) for team in pod) for pod in pods]
        ceiling = max(hard_size, max(sizes))
        current_cost = spread_cost(sizes)
        best_move = None
        for source in range(pod_count):
            for position, team in enumerate(pods[source]):
                for destination in range(pod_count):
                    if destination == source:
                        continue
                    trial = list(sizes)
                    trial[source] -= len(team)
                    trial[destination] += len(team)
                    if max(trial) > ceiling:
                        continue
                    cost = spread_cost(trial)
                    if cost < current_cost - 1e-9 and (best_move is None or cost < best_move[0]):
                        best_move = (cost, source, position, destination)
        if best_move is None:
            break
        _, source, position, destination = best_move
        pods[destination].append(pods[source].pop(position))

    return [
        sorted(member for team in pod for member in team)
        for pod in pods
        if pod
    ]


def size_shortfall(pods):
    """How many seats these pods are short of the soft minimum, added up."""
    return sum(max(0, SOFT_SIZE - len(pod)) for pod in pods)


def pack_category_into_pods(teams_by_event):
    """Build the pods for one event category.

    A written event with enough mentees to fill a pod is packed on its own, so
    a pod normally holds one event and nothing else. Events too small for that
    cannot, and leaving them alone is how a pod ends up with one person in it.
    Their teams are pooled instead and folded into whichever event in the same
    category leaves the fewest empty seats afterwards.
    """
    people_by_event = {
        event: sum(len(team) for team in teams) for event, teams in teams_by_event.items()
    }
    viable = sorted(e for e in teams_by_event if people_by_event[e] >= SOFT_SIZE)
    too_small = sorted(e for e in teams_by_event if people_by_event[e] < SOFT_SIZE)

    packed = {event: pack_teams_into_pods(teams_by_event[event]) for event in viable}
    flatten = lambda: [pod for event in viable for pod in packed[event]]
    if not too_small:
        return flatten()

    pooled_teams = [team for event in too_small for team in teams_by_event[event]]
    event_of_team = {id(team): event
                     for event, group in teams_by_event.items() for team in group}.get
    pooled = pack_teams_into_pods(pooled_teams, group_of=lambda team: event_of_team(id(team)))
    if not viable:
        return pooled

    best = None
    for event in viable:
        merged = pack_teams_into_pods(
            teams_by_event[event] + pooled_teams, group_of=lambda team: event_of_team(id(team))
        )
        change = size_shortfall(merged) - size_shortfall(packed[event]) - size_shortfall(pooled)
        ranking = (change, people_by_event[event], event)
        if best is None or ranking < best[0]:
            best = (ranking, event, merged)

    (change, _, _), host, merged = best
    if change > 0 and min(len(pod) for pod in pooled) > 1:
        return flatten() + pooled

    packed[host] = merged
    return flatten()


def required_experience(pod_members, mentees):
    """How many years in DECA a mentor needs to lead this pod, which is however
    long the most experienced mentee has been in it."""
    return pd.to_numeric(mentees.loc[pod_members, "years_number"], errors="coerce").max()


def clears_seniority(mentor_experience, needed_experience):
    """Whether a mentor has been in DECA at least as long as the pod needs.

    An unanswered year counts as clearing the bar, since the alternative is
    dropping a volunteer over a blank cell.
    """
    if pd.isna(needed_experience) or pd.isna(mentor_experience):
        return True
    return mentor_experience >= needed_experience


def seniority_margin(mentor_experience, needed_experience):
    """How far past the pod's requirement a mentor sits. Unknown years sort
    last so a filled in answer always wins a tie."""
    if pd.isna(mentor_experience) or pd.isna(needed_experience):
        return 99.0
    return abs(float(mentor_experience) - float(needed_experience))


def shortlist_mentors(pod, mentors, taken, same_event_only, require_seniority):
    """Everyone who could take this pod under one set of rules, tightest
    seniority fit first."""
    candidates = []
    for mentor_index in mentors.index:
        if mentor_index in taken:
            continue
        if same_event_only and mentors.at[mentor_index, "event_code"] != pod["event_code"]:
            continue
        experience = mentors.at[mentor_index, "years_number"]
        if require_seniority and not clears_seniority(experience, pod["needs"]):
            continue
        candidates.append(mentor_index)
    candidates.sort(key=lambda i: (
        seniority_margin(mentors.at[i, "years_number"], pod["needs"]),
        str(mentors.at[i, "last_name"]),
        str(mentors.at[i, "first_name"]),
    ))
    return candidates


def maximum_matching(options_by_pod, pod_order):
    """Pair off as many pods with their own mentor as the shortlists allow.

    This is the standard augmenting path search. When a pod wants a mentor who
    is already spoken for, it asks that pod to move to one of its other options,
    and the chain unwinds until either somebody shifts or the pod gives up.
    Trying pods one at a time and taking the first free mentor gets stuck far
    short of this, which is how one mentor ends up with three pods while nine
    others sit idle.
    """
    pod_holding = {}

    def try_to_place(pod, already_asked):
        for mentor in options_by_pod[pod]:
            if mentor in already_asked:
                continue
            already_asked.add(mentor)
            current = pod_holding.get(mentor)
            if current is None or try_to_place(current, already_asked):
                pod_holding[mentor] = pod
                return True
        return False

    for pod in pod_order:
        try_to_place(pod, set())
    return {pod: mentor for mentor, pod in pod_holding.items()}


def improve_event_matches(chosen, pods, mentors, ring_limit=3):
    """Rotate mentors between pods when the rotation puts more of them on their
    own written event.

    Serving the most experienced pods first protects the seniority rule but can
    leave a mentor coaching an event they never signed up for while a trade two
    pods over would fix both. This tries every mentor nobody ended up with, then
    every ring of up to three pods passing mentors around, and takes the first
    rotation that helps without dropping a pod below the experience it needs.
    """
    by_number = {pod["number"]: pod for pod in pods}
    numbers = sorted(chosen)

    def on_own_event(pod_number, mentor_index):
        return mentors.at[mentor_index, "event_code"] == by_number[pod_number]["event_code"]

    def fits(pod_number, mentor_index):
        return clears_seniority(mentors.at[mentor_index, "years_number"], by_number[pod_number]["needs"])

    def take_an_idle_mentor():
        idle = [m for m in mentors.index if m not in set(chosen.values())]
        for pod_number in numbers:
            if on_own_event(pod_number, chosen[pod_number]):
                continue
            for mentor_index in idle:
                if on_own_event(pod_number, mentor_index) and fits(pod_number, mentor_index):
                    chosen[pod_number] = mentor_index
                    return True
        return False

    def rotate():
        for size in range(2, ring_limit + 1):
            for ring in combinations(numbers, size):
                held = [chosen[number] for number in ring]
                if all(on_own_event(number, mentor) for number, mentor in zip(ring, held)):
                    continue
                best = sum(on_own_event(number, mentor) for number, mentor in zip(ring, held))
                for shuffled in permutations(held):
                    if shuffled == tuple(held):
                        continue
                    if not all(fits(number, mentor) for number, mentor in zip(ring, shuffled)):
                        continue
                    if sum(on_own_event(n, m) for n, m in zip(ring, shuffled)) > best:
                        for number, mentor in zip(ring, shuffled):
                            chosen[number] = mentor
                        return True
        return False

    while take_an_idle_mentor() or rotate():
        pass
    return chosen


def assign_mentors(pods, mentors):
    """Give every pod a mentor, one pod per mentor for as long as that lasts.

    Pods are served in order of how much DECA experience they need, so the pods
    holding a fourth year mentee get first call on the fourth year mentors
    instead of losing them to a group of freshmen who happened to be sorted
    earlier. Within one experience level the pods that share a written event
    with a free mentor are paired first, then the rest take whoever is left who
    still clears the bar.

    Anything still unpaired after that goes through two looser passes that drop
    the seniority rule and then the event rule. If more pods exist than mentors,
    the last few are handed to whoever is carrying the fewest mentees.
    """
    if mentors.empty:
        return {}

    chosen = {}
    taken = set()

    def run_pass(waiting, same_event_only, require_seniority):
        if not waiting or len(taken) == len(mentors.index):
            return
        options_by_pod = {
            pod["number"]: shortlist_mentors(pod, mentors, taken, same_event_only, require_seniority)
            for pod in waiting
        }
        ordered = sorted(waiting, key=lambda pod: (
            len(options_by_pod[pod["number"]]),
            -len(pod["members"]),
            pod["number"],
        ))
        for pod_number, mentor_index in maximum_matching(
            options_by_pod, [pod["number"] for pod in ordered]
        ).items():
            chosen[pod_number] = mentor_index
            taken.add(mentor_index)

    def demand(pod):
        return -1.0 if pd.isna(pod["needs"]) else float(pod["needs"])

    for level in sorted({demand(pod) for pod in pods}, reverse=True):
        for same_event_only in (True, False):
            run_pass(
                [pod for pod in pods if demand(pod) == level and pod["number"] not in chosen],
                same_event_only,
                True,
            )

    for same_event_only in (True, False):
        run_pass([pod for pod in pods if pod["number"] not in chosen], same_event_only, False)

    mentee_load = {mentor: 0 for mentor in mentors.index}
    by_number = {pod["number"]: pod for pod in pods}
    for pod_number, mentor_index in chosen.items():
        mentee_load[mentor_index] += len(by_number[pod_number]["members"])

    for pod in pods:
        if pod["number"] in chosen:
            continue
        pick = min(mentors.index, key=lambda i: (
            mentee_load[i],
            0 if clears_seniority(mentors.at[i, "years_number"], pod["needs"]) else 1,
            0 if mentors.at[i, "event_code"] == pod["event_code"] else 1,
            seniority_margin(mentors.at[i, "years_number"], pod["needs"]),
            str(mentors.at[i, "last_name"]),
            str(mentors.at[i, "first_name"]),
        ))
        chosen[pod["number"]] = pick
        mentee_load[pick] += len(pod["members"])

    return improve_event_matches(chosen, pods, mentors)


def open_when_possible(path):
    """Open the finished spreadsheet with whatever the operating system uses.

    The original call shelled out to macOS's open command, which fails anywhere
    else. Nothing here is worth crashing a finished run over, so a failure just
    prints a note.
    """
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as problem:
        print(f"Could not open {path} automatically ({problem}).")


def main(argv=None):
    """Read the responses, build the pods, and write the spreadsheet."""
    argv = sys.argv[1:] if argv is None else argv

    print("Reading:", INPUT_CSV)
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Can't find {INPUT_CSV}")

    frame = pd.read_csv(INPUT_CSV)
    frame.columns = frame.columns.str.strip()
    columns = list(frame.columns)

    timestamp_column = find_column(columns, "timestamp", default="Timestamp")
    email_column = find_column(columns, "email address", default="Email Address")
    first_name_column = find_column(columns, "first name", default="First Name")
    last_name_column = find_column(columns, "last name", default="Last Name")
    years_column = find_column(columns, "year in deca", default="Year in DECA")
    mentor_flag_column = find_mentor_flag_column(columns)
    category_column = find_column(columns, "select written event category")
    if category_column is None:
        raise KeyError("The form export has no 'Select Written Event Category' column.")
    written_columns = find_written_event_columns(columns, category_column)
    partner_name_column, partner_email_column = find_written_partner_columns(columns, category_column)

    print(f"Written event branches in use: {len(written_columns)}")
    print(f"Written event teammate columns: {partner_name_column!r}, {partner_email_column!r}")

    category_to_column = map_categories_to_branch_columns(frame, category_column, written_columns)

    frame["first_name"] = frame[first_name_column].fillna("").astype(str).str.strip()
    frame["last_name"] = frame[last_name_column].fillna("").astype(str).str.strip()
    frame["full_name"] = (frame["last_name"] + ", " + frame["first_name"]).str.strip(", ")
    frame["mentee_name_key"] = (frame["first_name"] + " " + frame["last_name"]).map(name_fingerprint)
    frame["email_name_key"] = (
        frame[email_column].map(normalize_email)
        .str.split("@").str[0].str.replace(r"[._]", " ", regex=True).map(name_fingerprint)
    )
    frame["mentee_email"] = frame[email_column].map(normalize_email)
    frame["years_number"] = frame[years_column].map(parse_years_in_deca)

    frame["event_name"] = frame.apply(
        lambda row: resolve_written_event(row, category_column, written_columns, category_to_column),
        axis=1,
    )
    frame["event_code"] = frame["event_name"].map(event_abbreviation)

    if partner_email_column:
        frame["partner_emails"] = frame[partner_email_column].map(split_partner_emails)
    else:
        frame["partner_emails"] = [[] for _ in range(len(frame))]
    if partner_name_column:
        frame["partner_names"] = frame[partner_name_column].map(split_partner_names)
    else:
        frame["partner_names"] = [[] for _ in range(len(frame))]

    raw_rows = len(frame)
    frame = frame[(frame["mentee_email"] != "") | (frame["full_name"] != "")]
    frame = frame[~frame.index.isin(
        frame[frame["mentee_email"] != ""].sort_values(timestamp_column, kind="stable")
        .duplicated("mentee_email", keep="last").pipe(lambda d: d[d].index)
    )]
    if len(frame) != raw_rows:
        print(f"Dropped {raw_rows - len(frame)} blank or repeat rows ({raw_rows} -> {len(frame)})")

    mentor_answers = frame[mentor_flag_column].astype(str).str.strip().str.lower()
    print("Mentor question answers:", dict(Counter(mentor_answers)))
    is_mentor = mentor_answers.isin({"yes", "y", "true"})
    mentors = frame[is_mentor].copy()
    mentees = frame[~is_mentor].copy()

    blank_events = int((frame["event_name"] == "").sum())
    print(f"Mentors who answered Yes: {len(mentors)}")
    print(f"Mentees: {len(mentees)}")
    print(f"Responses with a written event: {len(frame) - blank_events}/{len(frame)}")
    print("Note: the form never asks for school grade, so seniority uses Year in DECA.")

    teams, conflicts, mentor_teammates, missing = build_teams(mentees, frame)
    team_sizes = defaultdict(int)
    for team in teams:
        team_sizes[len(team)] += 1
    print("Teams by size:", dict(sorted(team_sizes.items())))
    if conflicts:
        print(f"Teammates who named each other but picked different written events: {len(conflicts)}")
        for left, right in conflicts:
            print(f"  {mentees.at[left, 'full_name']} ({mentees.at[left, 'event_name']})"
                  f"  vs  {mentees.at[right, 'full_name']} ({mentees.at[right, 'event_name']})")

    if mentor_teammates:
        pairs = {(mentees.at[a, "full_name"], frame.at[b, "full_name"]) for a, b in mentor_teammates}
        print(f"Mentees whose written event teammate is a mentor: {len(pairs)}")
        for mentee_name, mentor_name in sorted(pairs):
            print(f"  {mentee_name} competes with {mentor_name}, who is mentoring instead")
    if missing:
        wanted = {(mentees.at[index, "full_name"], text) for index, text in missing}
        print(f"Teammates named by someone but matching no response: {len(wanted)}")
        for mentee_name, text in sorted(wanted):
            print(f"  {mentee_name} named {text}")

    pods = []
    for _, category_rows in mentees.groupby(category_column):
        category_members = set(category_rows.index)
        teams_by_event = defaultdict(list)
        for team in teams:
            if team[0] in category_members:
                teams_by_event[mentees.at[team[0], "event_code"]].append(team)
        for members in pack_category_into_pods(dict(teams_by_event)):
            pods.append({"members": members})

    for pod in pods:
        spread = Counter(mentees.at[member, "event_code"] for member in pod["members"])
        pod["event_code"] = spread.most_common(1)[0][0]
        pod["events_held"] = len(spread)

    pods.sort(key=lambda pod: (mentees.at[pod["members"][0], "event_name"], pod["members"][0]))
    for pod_number, pod in enumerate(pods, start=1):
        pod["number"] = pod_number
        pod["needs"] = required_experience(pod["members"], mentees)

    chosen_mentor = assign_mentors(pods, mentors)

    rows = []
    unmatched_events = []
    mentee_load = defaultdict(int)
    for pod in pods:
        pod_number = pod["number"]
        mentor_index = chosen_mentor.get(pod_number)
        if mentor_index is None:
            mentor_first = mentor_last = mentor_event = ""
            mentor_years = ""
        else:
            mentee_load[mentor_index] += len(pod["members"])
            mentor_first = mentors.at[mentor_index, "first_name"]
            mentor_last = mentors.at[mentor_index, "last_name"]
            mentor_event = mentors.at[mentor_index, "event_name"]
            mentor_years = mentors.at[mentor_index, years_column]
            if mentors.at[mentor_index, "event_code"] != pod["event_code"]:
                unmatched_events.append(pod_number)

        for member in pod["members"]:
            person = mentees.loc[member]
            rows.append({
                "Pod": pod_number,
                "Mentor First Name": mentor_first,
                "Mentor Last Name": mentor_last,
                "Mentor Year in DECA": mentor_years,
                "Mentor Event": mentor_event,
                "Event": person["event_name"],
                "Mentee First Name": person["first_name"],
                "Mentee Last Name": person["last_name"],
                "Years in DECA": person[years_column],
                "Email": person[email_column],
                "Timestamp": person[timestamp_column],
            })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["Pod", "Mentee Last Name", "Mentee First Name"])
    result.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")

    pod_sizes = defaultdict(int)
    for pod in pods:
        pod_sizes[len(pod["members"])] += 1
    print(f"\nPods built: {len(pods)}")
    print("Pod sizes:", dict(sorted(pod_sizes.items())))
    below_soft = [len(pod["members"]) for pod in pods if len(pod["members"]) < SOFT_SIZE]
    if below_soft:
        print(f"Pods under {SOFT_SIZE}: {len(below_soft)}, smallest {min(below_soft)}")
    mixed = [pod for pod in pods if pod["events_held"] > 1]
    if mixed:
        print(f"Pods holding more than one written event: {len(mixed)}, because those events "
              f"were too small to fill a pod alone")
        for pod in mixed:
            spread = Counter(mentees.at[m, "event_name"] for m in pod["members"])
            print(f"  pod {pod['number']}: " + ", ".join(f"{name} x{n}" for name, n in spread.most_common()))
    if unmatched_events:
        print(f"Pods whose mentor signed up for a different written event: {len(unmatched_events)}")
    pods_per_mentor = defaultdict(int)
    for pod in pods:
        if chosen_mentor.get(pod["number"]) is not None:
            pods_per_mentor[chosen_mentor[pod["number"]]] += 1
    load_spread = defaultdict(int)
    for mentor_index in mentors.index:
        load_spread[mentee_load.get(mentor_index, 0)] += 1
    print(f"Mentors used: {len(pods_per_mentor)} of {len(mentors)}")
    print("Pods per mentor:", dict(sorted(defaultdict(
        int, {count: sum(1 for v in pods_per_mentor.values() if v == count)
              for count in set(pods_per_mentor.values())}).items())))
    print("Mentees per mentor:", dict(sorted(load_spread.items())))
    print(f"Wrote {len(result)} rows to {OUTPUT_XLSX}")

    if "--no-open" not in argv:
        open_when_possible(OUTPUT_XLSX)


if __name__ == "__main__":
    main()
