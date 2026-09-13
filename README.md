# DECA mentor pod sorting

> **This is not a new project.** It is a copy of [natmkk/DECA-](https://github.com/natmkk/DECA-), published here so my own contributions to it are readable in one place. The sorter was written by natmkk for our DECA chapter's mentor program. My first two commits were made in August 2026 on the `fix-pod-sorting` branch of the original repository, before this copy existed, so the early history here is just the import. The September 2026 rework of the pod rules was made in this copy. All of it is described under [What I contributed](#what-i-contributed).

Sorts DECA mentees into mentor pods for written events. It reads the merged Google Forms export holding both mentor and mentee responses, gives every mentor a pod in their written event cluster, puts each mentor's own written event teammates in that pod first, keeps declared mentee teams together, and fills the remaining seats from the same cluster. The output is a spreadsheet an adviser can hand out.

## What I contributed

The sorter was written by natmkk. My work is the two commits below, both made on August 12, 2026 in [natmkk/DECA-](https://github.com/natmkk/DECA-), on the `fix-pod-sorting` branch. Each heading links to the original commit, which is where the real history and dates live.

### Form parsing, pod packing and mentor assignment ([3744da5](https://github.com/natmkk/DECA-/commit/3744da5917fdce84068bb15c422ece224a1d48aa))

The script would not run against `MentorAndMenteeResponses.csv`, which is the export this repository ships. Once I got it running, the pods it produced did not reflect what people had actually filled in.

#### Reading the form

Mentors are identified by the "Are you a Mentor?" question. The old code looked for a column containing the word "role", which matches "Select Roleplay Category" first, and that column sits earlier in the export. No mentor was ever found. The script then fell back to writing out the most senior mentee in each pod as that pod's mentor, so the spreadsheet looked plausible while being wrong on every row. I changed the lookup to an exact match on the mentor question.

The written event question branches once per event category, so the export carries five separate columns all named some version of "Select Written", and each student has an answer in exactly one of them. Only the plainly named column was being read, which left most mentees with a blank event and dumped them into one undifferentiated group. I made the script read all five branches and take the one matching the student's answer to "Select Written Event Category". The pairing between a category and its branch column is worked out from where the answers actually landed rather than hardcoded, so a reworded category next season still reads correctly.

Teammates were being taken from the roleplay partner questions, which sit earlier in the export and ask almost the same thing as the written event ones. I pointed the parser at the written event questions instead. Emails now split on spaces as well as commas and newlines, names split on "and" and "&", and a name that matches nobody falls back to the local part of the email address, which recovers students whose partner typed their name wrong.

The old code also sorted on school grade. The form has no grade column, so I dropped that logic and ran seniority on Year in DECA, which the form does ask for, and renamed the output column to match.

#### Building pods

Pods aim at six or seven people. The previous packer moved solo mentees around one at a time, which meant a team of three could not be relocated and pods drifted well away from the target size. I made it work out up front how many pods a written event needs, aim every pod at an equal share, and move whole teams rather than individuals.

An event with fewer than six mentees cannot fill a pod on its own. Those mentees now join a pool for their event category, and the pool folds into whichever event in that category leaves the fewest empty seats, so nobody sits in a pod of one. Teams are laid down event by event inside a shared pod, so a pod carrying two events keeps them in blocks.

#### Assigning mentors

A mentor qualifies for a pod once they have spent at least as many years in DECA as the most experienced mentee in it. Assigning pods one at a time gives an early pod a mentor that a later, more demanding pod turns out to need, and the later pod then gets nobody. I replaced that with an augmenting path search over the pod and mentor pairs, serving the pods that need the most experience first. A cleanup pass then rotates mentors between pods whenever the rotation puts more of them on a pod running their own written event and no pod drops below the experience it needs.

#### Cross-platform opening and tests

Opening the finished spreadsheet used a macOS-only call, so I made it work on Windows and Linux too and added `--no-open` for scripted runs. A failure there now prints a note instead of ending the run badly. I also added `test_main.py`, 154 lines covering name matching, partner parsing, mentor column detection, branch column resolution, pod packing and mentor assignment.

The commit is 961 lines added and 300 removed across `main.py` and `test_main.py`.

### Rewriting the README (August) ([7c472d1](https://github.com/natmkk/DECA-/commit/7c472d13041a11a8800aedb5f795f667fbc4bd2e))

The old README described a mentor form with first and second event choices and a grade field. Neither exists in the export the repository ships, so the document read as a spec for a different program. I replaced it with how the script actually reads the form, builds pods, matches mentors, and what it warns you about at the end of a run. That text is what the rest of this file is based on.

### Cluster pods, mentor teammates and co-presidents (September 2026)

The chapter changed what a pod should be. A pod now belongs to a mentor rather than to a written event, and the rules run in this order. A mentor's own written event teammates go in that mentor's pod. Mentees who named each other stay together. The rest of the pod is filled from the mentor's written event cluster.

That replaced the event packer and the mentor matching search with one pass that works cluster by cluster. Each cluster gets as many pods as its headcount needs at seven a pod, then any mentors left over are handed to whichever cluster has the fullest pods, as long as the average stays at five or above. Clusters short on mentors borrow from the no-written mentors first and then from clusters with spares. Within a pod the mentor's teammates are pinned, remaining teams are laid down event by event so a pod tends to hold one event, and whole teams move between pods until the sizes settle.

Co-presidents are read from a new "Are you a Co-President?" column. They are dropped from both the mentor and mentee lists and never appear in the output, while the teammates they named are sorted as ordinary mentees. Teammate answers are read from mentor rows as well as mentee rows, so a link declared from either side counts.

Mentors only lead clusters they have competed in. `PreviousYearRegistrationData.csv` is the prior year's form export, and each mentor is looked up in it by warriorlife address, falling back to name when the address changed. The written event found there decides which cluster the mentor's pod belongs to, whatever they picked this year, while the mentor's own teammates come along into that pod regardless. A mentor with no past record can lead any cluster, and the run says so. When a cluster has more pods than past mentors, the extra pods borrow whoever is spare and the run lists them.

The cluster membership lives in `WrittenEventClusters.xlsx`, one row per cluster with its events listed the way the form names them, matched on the code in parentheses. That file was built from the DECA high school competitive events list and covers events the form does not currently offer, so a new branch next season needs no code change.

Mentorship then asked for larger pods so more of a cluster sits together. The run now asks for a maximum pod size and whether to fill pods to that maximum in turn or spread mentees evenly. Each mentor still leads exactly one pod, so raising the cap lets a cluster short on mentors keep its mentees together instead of borrowing a mentor from elsewhere.

The analytics team tracks attendance in a sheet with eight fixed columns, so the run also writes `MentorPodAttendance.xlsx` in that layout. Each pod lists its mentor first with a blank Status, then the mentees marked Compete. Level comes from `ExpectedExperiencedNoviceMentee.xlsx` by address, and anyone missing from it is filled in from Year in DECA.

## How it works

Mentees who named each other as written event teammates form a team, and a team is never split across pods. Matching runs on warriorlife addresses first and falls back to names, with the words sorted before comparison so "Kavya Wahlberg" and "Wahlberg, Kavya" reach the same person. Names are also checked against the local part of each address, which recovers people whose name field holds a typo. Teammates join up even when they picked different written events, and the team lands in the cluster most of its members picked, with the mismatch printed so an advisor can chase it. Teammate answers on mentor rows are read as well, so a mentor who lists a mentee, or a mentee who lists a mentor, produces the same link.

Every written event maps to a cluster through `WrittenEventClusters.xlsx`. An event missing from that sheet falls back to the form's "Select Written Event Category" answer.

A mentor's cluster comes from the written event they did last year, read from `PreviousYearRegistrationData.csv`. The lookup runs on the warriorlife address first and falls back to the name when someone registered with a different address. A mentor's own teammates always sit in that mentor's pod, even when the teammates' event is in a different cluster from the mentor's past event, and the run lists each case. A mentor with no past record can lead any cluster.

`ManualPlacements.csv` holds exceptions, one row per mentee with the mentee's address and the mentor's address. Each one is pinned into that mentor's pod the same way a teammate is, and the run lists the rows it applied and any it could not match.

Pods are built one cluster at a time.

1. A mentor whose written event teammates are mentees gets a pod in that cluster with those teammates in it. A mentee named by two mentors stays with the first, and the run says so.
2. Mentee teams stay whole.
3. The rest of the cluster's teams fill the pods. Each team goes to the pod that still has room, whose mentor has been in DECA at least as long as the team's most experienced member, that already holds the team's event, and that is furthest from its target size, in that order. Whole teams then move between pods until the sizes stop getting closer together. With overflow on, the size checks drop out and pods fill in order.

The run starts by asking two questions in the terminal. Whether to enable overflow, and the maximum pod size, which defaults to seven. Every pod has exactly one mentor. With overflow off, each mentor who has competed in a cluster gets a pod there, so a cluster with nine mentors has nine pods however large the cap is, and teams are spread so those pods come out even. A cluster whose mentees would not fit under the cap that way takes pods, and the mentors who go with them, from the cluster whose pods are emptiest. With overflow on, each cluster has only as many pods as its headcount needs at the cap, each pod fills to the cap before the next one starts, and the mentors left over sit out and are listed.

Mentors are ranked for a pod by whether they have teammates to lead, then by years in DECA. A mentee named by two mentors stays with the first. A cluster with no mentor of its own borrows first from mentors with no past record, then from clusters with spares, and the run lists every pod led by a mentor outside their past cluster.

Co-presidents answer Yes in the "Are you a Co-President?" column. They are left out of the mentor list and the mentee list, so they get no pod and lead none, while the teammates they named are sorted like anyone else.

## What the run warns you about

The end of a run prints these lists, all worth chasing before competition.

- Co-presidents skipped, and mentees whose named teammate is a co-president.
- Teammates who named each other but picked different written events. They stay together, so one of them is competing outside the pod's cluster.
- Mentors whose written event teammate is a mentee, and any mentee two mentors both claimed.
- Mentors matched to last year's data by name rather than address, and mentors with no past record at all.
- Teammates kept in their mentor's pod even though their own event belongs to a different cluster.
- Manual placements applied, and any row in `ManualPlacements.csv` that matches nobody in the export.
- Teammates named by somebody but matching no response, usually a misspelled address or a student who never filled the form in.
- Returning mentees with no row in the level sheet, and the level they were given from Year in DECA.
- Pods carrying more than one written event, pods whose mentor has not competed in that cluster, pods where a mentee has more years in DECA than the mentor, and mentors left without a pod.

## Known limits

The form never asks for school grade, so seniority runs entirely on Year in DECA. Seniority is a preference during filling rather than a hard rule, and the run lists the pods where it could not be kept.

Clusters short on mentors borrow from elsewhere in the club, and the run prints how many pods that affects.

## Running it

```
pip install pandas openpyxl
python main.py
```

Before it reads anything the script asks two questions. Type `y` or `n` for the first, a whole number for the second, or press Enter to take the default.

```
Enable overflow, filling each pod to the max before starting the next? [y/N]: n
Max pod size [7]: 15
Max pod size 15, overflow off
```

Answer `n` and every mentor leads a pod in their cluster, with mentees spread evenly under the cap. Answer `y` and each cluster opens only as many pods as fit under the cap, fills them in turn, and any mentor without a pod is listed at the end of the run. Mentorship's setting for 2026-27 is no overflow with a cap of 15.

The script then reads `MentorAndMenteeResponses.csv`, `PreviousYearRegistrationData.csv`, `WrittenEventClusters.xlsx`, `ExpectedExperiencedNoviceMentee.xlsx` and `ManualPlacements.csv` from its own folder, writes `MentorPodSorting.xlsx` and `MentorPodAttendance.xlsx` beside it, and opens the pod spreadsheet. Pass `--no-open` to skip that last step.

The export needs an "Are you a mentor?" column and, to skip co-presidents, an "Are you a Co-President?" column, both answered Yes or No. Blank rows, repeated header rows and repeat submissions from one address are dropped before sorting, and the run prints how many.

`python test_main.py` runs the self checks.

## What comes out

One row per mentee, sorted by pod.

| Column | Meaning |
| --- | --- |
| Pod | Pod number, counting up from 1, grouped by cluster |
| Mentor First Name, Mentor Last Name | Who is running the pod |
| Mentor Year in DECA | How long that mentor has been in DECA |
| Mentor Event | The written event the mentor signed up for this year, blank when the mentor has advisor permission to skip a written |
| Mentor Past Event | The written event the mentor competed in last year, which is what the pod's cluster is based on |
| Cluster | The written event cluster the pod belongs to |
| Event | The written event the mentee signed up for |
| Mentee First Name, Mentee Last Name | The mentee |
| Years in DECA, Email, Timestamp | Carried straight through from the form |
| Mentor's Teammate | Yes when this mentee is the mentor's own written event teammate or a manual placement |

### The attendance sheet

`MentorPodAttendance.xlsx` is every pod in the layout the analytics team's attendance tracker expects, columns A through H, ready to paste in. Each pod starts with its mentor's own row, then the mentees.

| Column | Meaning |
| --- | --- |
| Mentor Pod # | Pod number |
| Mentor Name(s) | Mentor first and last name |
| Email, First Name, Last Name, Event | The person on that row, mentor or mentee |
| Status | Compete for mentees, blank for mentors since they are officers |
| Level | Mentors are Experienced. Mentees take Novice or Experienced from `ExpectedExperiencedNoviceMentee.xlsx`, matched by address. A mentee missing from that sheet is Experienced from the third year in DECA on and Novice before that, and the run prints who was filled in that way |

## A note on the data in this repository

`MentorAndMenteeResponses.csv` is generated sample data. The real form carried student names and school email addresses, which are not published here.

The sample export keeps the same shape as the real one. It has the same 208 responses, the same 33 mentors, the same spread of Year in DECA answers, the same event mix across all five written branches, and the same team sizes. The messy parts were kept as well, including partners who named each other while picking different events, partners who are mentors, misspelled email domains, and names entered in a different order than the roster has them. Two mentors are marked as co-presidents so that path runs on the sample too.

`ExpectedExperiencedNoviceMentee.xlsx` is the real level sheet for returning members. `PreviousYearRegistrationData.csv` is the real prior year export, kept here so the next team can run the sorter without hunting for it. Because the sample responses use generated names and addresses, none of the sample mentors match it, so a run on the sample places every mentor as having no past record. Drop in the real current year export and the lookup matches.
