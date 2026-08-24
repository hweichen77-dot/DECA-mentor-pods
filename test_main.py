"""Self checks for the pod sorter.

Run it with python test_main.py. Every check is an assert, so silence means the
logic that the pod sorting depends on still behaves.
"""

import pandas as pd

import main


def check_name_matching():
    """Two spellings of one person have to land on the same key, because the
    form stores first and last name in separate columns while students type
    teammates as one string and sometimes reverse the order."""
    assert main.name_fingerprint("Litian Gu") == main.name_fingerprint("gu,  LITIAN")
    assert main.name_fingerprint("Amber Chang") != main.name_fingerprint("Amber Chan")


def check_partner_parsing():
    """Teammate answers arrive separated by commas, newlines or plain spaces,
    and a good number of them say some version of no partner."""
    two_emails = "Adithi.Jha@warriorlife.net Litian.Gu@warriorlife.net"
    assert main.split_partner_emails(two_emails) == [
        "adithi.jha@warriorlife.net",
        "litian.gu@warriorlife.net",
    ]
    assert main.split_partner_emails("a@b.net\nc@d.net") == ["a@b.net", "c@d.net"]
    assert main.split_partner_emails("N/A") == []
    assert main.split_partner_names("Kayla Tan\nChloe Zhong") == [
        ("kayla", "tan"),
        ("chloe", "zhong"),
    ]
    assert main.split_partner_names("na") == []
    assert main.split_partner_names("Amber") == []


def check_event_helpers():
    assert main.event_abbreviation("Innovation Plan (EIP)") == "EIP"
    assert main.parse_years_in_deca("3rd Year") == 3
    assert pd.isna(main.parse_years_in_deca("op"))


def check_mentor_column_is_not_the_roleplay_one():
    """A loose keyword search for the word role matches Select Roleplay Category
    first and turns every mentor into a mentee, so the match has to be exact."""
    headers = ["Timestamp", "Select Roleplay Category", "Are you a Mentor?"]
    assert main.find_mentor_flag_column(headers) == "Are you a Mentor?"


def check_written_event_branches():
    """The written event answer lives in whichever branch column matches the
    category the student chose, even when an earlier branch still holds a
    leftover answer from before they switched."""
    frame = pd.DataFrame({
        "Select Written Event Category": ["Alpha", "Alpha", "Beta", "Beta"],
        "Select Written": ["A one", "A two", "leftover", None],
        "Select Written.1": [None, None, "B one", "B two"],
    })
    category = "Select Written Event Category"
    branches = main.find_written_event_columns(frame.columns, category)
    assert branches == ["Select Written", "Select Written.1"]
    mapping = main.map_categories_to_branch_columns(frame, category, branches)
    assert mapping == {"Alpha": "Select Written", "Beta": "Select Written.1"}
    picked = [main.resolve_written_event(row, category, branches, mapping)
              for _, row in frame.iterrows()]
    assert picked == ["A one", "A two", "B one", "B two"]


def check_pod_packing():
    """Pods come out evenly sized, no team gets broken up, and nobody goes
    missing along the way."""
    solos = [[i] for i in range(20)]
    pods = main.pack_teams_into_pods(solos)
    assert sorted(len(pod) for pod in pods) == [6, 7, 7]

    fifteen = [[i] for i in range(15)]
    assert sorted(len(pod) for pod in main.pack_teams_into_pods(fifteen)) == [5, 5, 5]

    ten = [[0, 1, 2], [3, 4, 5], [6, 7], [8], [9]]
    pods = main.pack_teams_into_pods(ten)
    assert sorted(len(pod) for pod in pods) == [5, 5]
    for team in ten:
        holder = [pod for pod in pods if team[0] in pod]
        assert len(holder) == 1 and set(team) <= set(holder[0])

    everyone = sorted(person for pod in pods for person in pod)
    assert everyone == list(range(10))

    assert main.pack_teams_into_pods([]) == []
    assert main.pack_teams_into_pods([[0], [1]]) == [[0, 1]]


def make_pod(number, event_code, members, needs):
    return {"number": number, "event_code": event_code, "members": members, "needs": needs}


def check_mentor_assignment():
    """Every pod gets its own mentor, nobody leads a pod full of people who have
    been in DECA longer than they have, and the pods that need a fourth year get
    the fourth years."""
    mentors = pd.DataFrame(
        {
            "years_number": [2.0, 4.0, 4.0],
            "event_code": ["EIP", "ESB", "EIP"],
            "first_name": ["Ana", "Ben", "Cal"],
            "last_name": ["A", "B", "C"],
        },
        index=[10, 11, 12],
    )
    pods = [
        make_pod(1, "EIP", [0, 1], 4.0),
        make_pod(2, "ESB", [2, 3], 4.0),
        make_pod(3, "EIP", [4, 5], 1.0),
    ]
    chosen = main.assign_mentors(pods, mentors)
    assert sorted(chosen) == [1, 2, 3]
    assert len(set(chosen.values())) == 3
    assert chosen[1] == 12
    assert chosen[2] == 11
    assert chosen[3] == 10

    for pod in pods:
        mentor = chosen[pod["number"]]
        assert main.clears_seniority(mentors.at[mentor, "years_number"], pod["needs"])


def check_swaps_recover_event_matches():
    """A pair swap has to fire when the first pass hands two mentors the wrong
    event and trading them fixes both."""
    mentors = pd.DataFrame(
        {
            "years_number": [4.0, 4.0],
            "event_code": ["EIP", "ESB"],
            "first_name": ["Ana", "Ben"],
            "last_name": ["A", "B"],
        },
        index=[10, 11],
    )
    pods = [make_pod(1, "EIP", [0], 1.0), make_pod(2, "ESB", [1], 1.0)]
    fixed = main.improve_event_matches({1: 11, 2: 10}, pods, mentors)
    assert fixed == {1: 10, 2: 11}


if __name__ == "__main__":
    check_name_matching()
    check_partner_parsing()
    check_event_helpers()
    check_mentor_column_is_not_the_roleplay_one()
    check_written_event_branches()
    check_pod_packing()
    check_mentor_assignment()
    check_swaps_recover_event_matches()
    print("All checks passed.")
