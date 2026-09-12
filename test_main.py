import pandas as pd

import main


def check_name_matching():
    assert main.name_fingerprint("Litian Gu") == main.name_fingerprint("gu,  LITIAN")
    assert main.name_fingerprint("Amber Chang") != main.name_fingerprint("Amber Chan")


def check_partner_parsing():
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
    headers = ["Timestamp", "Select Roleplay Category", "Are you a Mentor?"]
    assert main.find_mentor_flag_column(headers) == "Are you a Mentor?"


def check_written_event_branches():
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


def check_co_president_column():
    headers = ["Timestamp", "Are you a mentor?", "Are you a Co-President?"]
    assert main.find_co_president_column(headers) == "Are you a Co-President?"
    assert main.find_co_president_column(["Timestamp", "Are you a mentor?"]) is None
    assert main.answered_yes(pd.Series(["Yes", "no", " YES ", None])).tolist() == [True, False, True, False]


def check_cluster_lookup():
    lookup = main.load_cluster_lookup(main.CLUSTER_XLSX)
    assert lookup["EIP"] == "Entrepreneurship Events"
    assert lookup["HTOR"] == "Business Operations Research Events"
    assert lookup["PMCG"] == "Project Management Events"
    assert len(set(lookup.values())) == 5
    suffixed = main.event_abbreviation("Business Growth Plan (EBG) *Must show legal proof of business ownership*")
    assert main.cluster_of(suffixed, "Entrepreneurship Events", lookup) == "Entrepreneurship Events"
    assert main.cluster_of("ZZZ", "Some New Category", lookup) == "Some New Category"
    assert main.cluster_of("", "Entrepreneurship Events", lookup) == ""
    assert main.cluster_of("ZZZ", "I have permission from advisors to NOT do a written", lookup) == ""


def people(rows):
    frame = pd.DataFrame(rows, columns=["first_name", "last_name", "years_number", "event_code", "cluster"])
    frame["mentee_email"] = (frame["first_name"] + "@x.net").str.lower()
    frame["mentee_name_key"] = [main.name_fingerprint(f + " " + l) for f, l in zip(frame["first_name"], frame["last_name"])]
    frame["email_name_key"] = frame["mentee_email"].str.split("@").str[0].map(main.name_fingerprint)
    frame["partner_emails"] = [[] for _ in rows]
    frame["partner_names"] = [[] for _ in rows]
    return frame


def check_build_pods():
    mentors = people([
        ("Ana", "A", 4.0, "EIP", "Entrepreneurship Events"),
        ("Ben", "B", 3.0, "ESB", "Entrepreneurship Events"),
        ("Cal", "C", 4.0, "BOR", "Business Operations Research Events"),
    ])
    mentors.index = [100, 101, 102]
    mentees = people(
        [(f"M{i}", "E", 1.0, "EIP" if i < 5 else "ESB", "Entrepreneurship Events") for i in range(10)]
        + [(f"M{i}", "B", 2.0, "BOR", "Business Operations Research Events") for i in range(10, 16)]
        + [("Loose", "L", 1.0, "", "")]
    )
    teams = [[0, 1], [2], [3], [4], [5, 6, 7], [8], [9], [10, 11], [12], [13], [14], [15], [16]]
    mentor_links = {101: {5}}
    pods, borrowed, idle, contested, unseated = main.build_pods(teams, mentees, mentors, mentor_links)

    assert not borrowed and not idle and not contested and not unseated
    assert sorted(member for pod in pods for member in pod["members"]) == list(range(17))
    ben_pod = next(pod for pod in pods if pod["mentor"] == 101)
    assert {5, 6, 7} <= set(ben_pod["members"])
    assert ben_pod["seeded"] == [5, 6, 7]
    for team in teams:
        holders = [pod for pod in pods if team[0] in pod["members"]]
        assert len(holders) == 1 and set(team) <= set(holders[0]["members"])
    for pod in pods:
        assert len(pod["members"]) <= main.HARD_SIZE
        for member in pod["members"]:
            assert mentees.at[member, "cluster"] in ("", pod["cluster"])
    assert next(pod for pod in pods if pod["mentor"] == 102)["cluster"] == "Business Operations Research Events"


def check_build_pods_borrows_spare_mentors():
    mentors = people([
        ("Ana", "A", 4.0, "BOR", "Business Operations Research Events"),
        ("Ben", "B", 4.0, "BOR", "Business Operations Research Events"),
        ("Cal", "C", 2.0, "", ""),
    ])
    mentors.index = [100, 101, 102]
    mentees = people([(f"M{i}", "E", 1.0, "EIP", "Entrepreneurship Events") for i in range(12)])
    teams = [[i] for i in range(12)]
    pods, borrowed, idle, contested, unseated = main.build_pods(teams, mentees, mentors, {})
    assert len(pods) == 2
    assert sorted(len(pod["members"]) for pod in pods) == [6, 6]
    assert {mentor for mentor, _ in borrowed} == {102, 100}
    assert idle == [101]


def check_seeded_mentors_capped_by_cluster_size():
    mentors = people([(f"A{i}", "A", 4.0, "PMBS", "Project Management Events") for i in range(4)])
    mentors.index = [100, 101, 102, 103]
    mentees = people([(f"M{i}", "P", 1.0, "PMBS", "Project Management Events") for i in range(5)])
    teams = [[i] for i in range(5)]
    links = {100: {0}, 101: {1}, 102: {2}, 103: {3}}
    pods, borrowed, idle, contested, unseated = main.build_pods(teams, mentees, mentors, links)
    assert len(pods) == 1 and len(pods[0]["members"]) == 5
    assert pods[0]["mentor"] == 100 and pods[0]["seeded"] == [0]
    assert unseated == [101, 102, 103]


if __name__ == "__main__":
    check_name_matching()
    check_partner_parsing()
    check_event_helpers()
    check_mentor_column_is_not_the_roleplay_one()
    check_written_event_branches()
    check_co_president_column()
    check_cluster_lookup()
    check_build_pods()
    check_build_pods_borrows_spare_mentors()
    check_seeded_mentors_capped_by_cluster_size()
    print("All checks passed.")
