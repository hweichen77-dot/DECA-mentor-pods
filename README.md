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

The cluster membership lives in `WrittenEventClusters.xlsx`, one row per cluster with its events listed the way the form names them, matched on the code in parentheses. That file was built from the DECA high school competitive events list and covers events the form does not currently offer, so a new branch next season needs no code change.

## How it works

Mentees who named each other as written event teammates form a team, and a team is never split across pods. Matching runs on warriorlife addresses first and falls back to names, with the words sorted before comparison so "Kavya Wahlberg" and "Wahlberg, Kavya" reach the same person. Names are also checked against the local part of each address, which recovers people whose name field holds a typo. Two mentees only join up when they picked the same written event. Teammate answers on mentor rows are read as well, so a mentor who lists a mentee, or a mentee who lists a mentor, produces the same link.

Every written event maps to a cluster through `WrittenEventClusters.xlsx`. An event missing from that sheet falls back to the form's "Select Written Event Category" answer.

Pods are built one cluster at a time.

1. A mentor whose written event teammates are mentees gets a pod in that cluster with those teammates in it. A mentee named by two mentors stays with the first, and the run says so.
2. Mentee teams stay whole.
3. The rest of the cluster's teams fill the pods. Each team goes to the pod that still has room, whose mentor has been in DECA at least as long as the team's most experienced member, that already holds the team's event, and that is furthest from its target size, in that order. Whole teams then move between pods until the sizes stop getting closer together.

Each cluster gets as many pods as its headcount needs at seven per pod. Mentors left over after that are given to the cluster with the fullest pods, as long as that cluster's average stays at five or more. A cluster with more pods than mentors of its own borrows first from mentors who are not doing a written event, then from clusters with spare mentors. Mentors are ranked for a pod by whether they have teammates to lead, then by years in DECA.

Co-presidents answer Yes in the "Are you a Co-President?" column. They are left out of the mentor list and the mentee list, so they get no pod and lead none, while the teammates they named are sorted like anyone else.

## What the run warns you about

The end of a run prints these lists, all worth chasing before competition.

- Co-presidents skipped, and mentees whose named teammate is a co-president.
- Teammates who named each other but picked different written events. One of the two lands in the wrong pod whatever the sorter does.
- Mentors whose written event teammate is a mentee, kept in the mentor's pod, and any mentee two mentors both claimed.
- Mentors whose cluster is too small to give them a pod of their own, so their teammate is sorted without them.
- Teammates named by somebody but matching no response, usually a misspelled address or a student who never filled the form in.
- Pods carrying more than one written event, pods whose mentor comes from a different cluster, pods where a mentee has more years in DECA than the mentor, and mentors left without a pod.

## Known limits

The form never asks for school grade, so seniority runs entirely on Year in DECA. Seniority is a preference during filling rather than a hard rule, and the run lists the pods where it could not be kept.

Clusters short on mentors borrow from elsewhere in the club, and the run prints how many pods that affects.

## Running it

```
pip install pandas openpyxl
python main.py
```

The script reads `MentorAndMenteeResponses.csv` and `WrittenEventClusters.xlsx` from its own folder, writes `MentorPodSorting.xlsx` beside it, and opens the spreadsheet. Pass `--no-open` to skip that last step.

The export needs an "Are you a mentor?" column and, to skip co-presidents, an "Are you a Co-President?" column, both answered Yes or No. Blank rows, repeated header rows and repeat submissions from one address are dropped before sorting, and the run prints how many.

`python test_main.py` runs the self checks.

## What comes out

One row per mentee, sorted by pod.

| Column | Meaning |
| --- | --- |
| Pod | Pod number, counting up from 1, grouped by cluster |
| Mentor First Name, Mentor Last Name | Who is running the pod |
| Mentor Year in DECA | How long that mentor has been in DECA |
| Mentor Event | The written event the mentor signed up for, blank when the mentor has advisor permission to skip a written |
| Cluster | The written event cluster the pod belongs to |
| Event | The written event the mentee signed up for |
| Mentee First Name, Mentee Last Name | The mentee |
| Years in DECA, Email, Timestamp | Carried straight through from the form |
| Mentor's Teammate | Yes when this mentee is the mentor's own written event teammate |

## A note on the data in this repository

`MentorAndMenteeResponses.csv` is generated sample data. The real form carried student names and school email addresses, which are not published here.

The sample export keeps the same shape as the real one. It has the same 208 responses, the same 33 mentors, the same spread of Year in DECA answers, the same event mix across all five written branches, and the same team sizes. The messy parts were kept as well, including partners who named each other while picking different events, partners who are mentors, misspelled email domains, and names entered in a different order than the roster has them. Two mentors are marked as co-presidents so that path runs on the sample too. Running the sorter against it produces 31 pods holding 175 mentees.
