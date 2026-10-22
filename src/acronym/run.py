import os
import re
import pandas as pd

from src.acronym.task_init import AcronymGenTaskInit
from src.acronym.task_iterate import AcronymGenTaskIterate
from src.acronym.feedback import AcronymGenFeedback
from src.utils import retry_parse_fail_prone_cmd

ENGINE = os.getenv("LLM_ENGINE", "gemini-1.5-flash")


@retry_parse_fail_prone_cmd
def iterative_acronym(title: str, max_attempts: int) -> str:

    # initialize all the required components

    # generation of the first acronym
    task_init = AcronymGenTaskInit(engine=ENGINE, prompt_examples="data/prompt/acronym/init.jsonl")

    # getting feedback
    task_feedback = AcronymGenFeedback(engine=ENGINE, prompt_examples="data/prompt/acronym/feedback.jsonl")

    # iteratively improving the acronym
    task_iterate = AcronymGenTaskIterate(engine=ENGINE, prompt_examples="data/prompt/acronym/feedback.jsonl")


    # Initialize the task

    n_attempts = 0

    print(f"{n_attempts} INIT> {title}")
    acronyms_to_scores = dict()

    all_acronyms_to_scores = dict()
    best_score_so_far = 0
    while n_attempts < max_attempts:

        if n_attempts == 0:
            acronym = task_init(title=title)
        else:
            new_title, acronym = task_iterate(acronyms_to_scores=acronyms_to_scores)
            title = new_title


        scores = task_feedback(title=title, acronym=acronym)
        score_match = re.search(r"Total\s*score:?\s*\*?\*?\s*(\d+)/(\d+)", scores, re.IGNORECASE)
        if score_match:
            total_score = int(score_match.group(1))
        else:
            found_scores = re.findall(r"(\d+)/5", scores)
            if found_scores:
                total_score = sum(int(s) for s in found_scores)
            else:
                total_score = 15

        all_acronyms_to_scores[acronym] = {
            "scores": scores,
            "total_score": total_score,
            "title": title,
            "iteration": n_attempts,
        }

        # Clean step printing
        step_label = "INITIAL GENERATION (Attempt 0)" if n_attempts == 0 else f"REFINEMENT STEP {n_attempts}"
        print(f"\n========================================================")
        print(f" >>> [{step_label}]")
        print(f"========================================================")
        print(f"Title / Focus : {title}")
        print(f"Candidate     : {acronym}")
        print(f"Total Score   : {total_score}/25")
        print(f"\nFeedback Critique:")
        for line in scores.strip().split("\n"):
            line = line.strip()
            if line:
                print(f"   {line}")

        if total_score >= 0:
            best_score_so_far = total_score
            acronyms_to_scores[acronym] = (title, scores)
        else:
            print(f"\n[Notice] Score of {acronym} is {total_score}, which did not beat current best of {best_score_so_far}")

        n_attempts += 1

    return all_acronyms_to_scores


def run_over_titles(titles_file: str, max_attempts: int, outfile: str):

    def _parse_results(title: str) -> str:
        try:
            results = iterative_acronym(title=title, max_attempts=max_attempts)
            if results is None:
                return "FAILED"
            res = []
            for acronym, scores in results.items():
                res.append(f"{acronym} [score: {scores['total_score']}] \n {scores['scores']}")
            return "\n ------ \n ".join(res)
        except Exception as e:
            return "FAILED"


    data = pd.read_csv(titles_file, sep="\t")
    data['generated_acronym'] = data['title'].apply(_parse_results)

    data.to_json(outfile, orient="records", lines=True)

if __name__ == "__main__":
    import sys
    title = sys.argv[1]
    if len(sys.argv) > 2:
        run_over_titles(titles_file=sys.argv[1], max_attempts=int(sys.argv[2]), outfile=sys.argv[3])
    else:
        max_attempts = 5
        print(f"\n========================================================")
        print(f" STARTING SELF-REFINE FOR TITLE:")
        print(f" \"{title}\"")
        print(f" Max Iterations: {max_attempts}")
        print(f"========================================================")

        all_acronyms_to_scores = iterative_acronym(
            title=title,
            max_attempts=max_attempts,
        )

        # Find best candidate
        best_candidate = None
        best_score = -1
        initial_candidate = None
        initial_score = -1

        for idx, (acronym, details) in enumerate(all_acronyms_to_scores.items()):
            if idx == 0:
                initial_candidate = acronym
                initial_score = details["total_score"]
            if details["total_score"] > best_score:
                best_score = details["total_score"]
                best_candidate = (acronym, details)

        print("\n" + "=" * 60)
        print("                 REFINEMENT SUMMARY")
        print("=" * 60)
        print(f"{'Step':<8} {'Acronym':<15} {'Score':<10} {'Status'}")
        print("-" * 60)
        for idx, (acronym, details) in enumerate(all_acronyms_to_scores.items()):
            is_best = (acronym == best_candidate[0])
            status = "★ BEST (ACCEPTED)" if is_best else ("Initial Draft" if idx == 0 else "Refined")
            print(f"{idx:<8} {acronym:<15} {details['total_score']}/25     {status}")
        print("-" * 60)

        # Highlight final accepted result
        best_acronym, best_details = best_candidate
        print(f"\n" + "#" * 60)
        print(f"               FINAL ACCEPTED RESULT")
        print(f"#" * 60)
        print(f"Acronym           : {best_acronym}")
        print(f"Final Score       : {best_details['total_score']}/25 (Started at {initial_score}/25 -> +{best_details['total_score'] - initial_score} improvement)")
        print(f"Associated Title  : {best_details['title']}")
        print(f"\nEvaluation Details:")
        for line in best_details['scores'].strip().split("\n"):
            if line.strip():
                print(f"   {line.strip()}")
        print(f"#" * 60 + "\n")
