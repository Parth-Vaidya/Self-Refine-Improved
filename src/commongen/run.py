import os
import pathlib
from tqdm import tqdm
from typing import List

from src.commongen.task_init import CommongenTaskInit
from src.commongen.task_iterate import CommongenTaskIterate
from src.commongen.feedback import CommongenFeedback
from src.utils import retry_parse_fail_prone_cmd

ENGINE = os.getenv("LLM_ENGINE", "gemini-1.5-flash")



@retry_parse_fail_prone_cmd
def autofb_commongen(concepts: List[str], max_attempts: int) -> str:

    # initialize all the required components

    # generation of the first sentence
    task_init = CommongenTaskInit(engine=ENGINE, prompt_examples="data/prompt/commongen/init.jsonl")

    # getting feedback
    task_feedback = CommongenFeedback(
        engine=ENGINE, prompt_examples="data/prompt/commongen/feedback.jsonl"
    )

    # iteratively improving the sentence
    task_iterate = CommongenTaskIterate(
        engine=ENGINE, prompt_examples="data/prompt/commongen/iterate.jsonl"
    )

    # Initialize the task
    n_attempts = 0
    sent_to_fb = []

    print(f"\n========================================================")
    print(f" STARTING COMMONGEN SELF-REFINE")
    print(f" Input Concepts : {concepts}")
    print(f" Max Iterations : {max_attempts}")
    print(f"========================================================")

    while n_attempts < max_attempts:
        if n_attempts == 0:
            sent = task_init(concepts=concepts)
        else:
            sent = task_iterate(concepts=concepts, sent_to_fb=sent_to_fb)

        concept_fb, commonsense_fb = task_feedback(concepts=concepts, sentence=sent)

        sent_to_fb.append(
            {
                "sentence": sent,
                "concept_feedback": [f.strip() for f in concept_fb.split(",")],
                "commonsense_feedback": commonsense_fb,
            }
        )

        step_label = "INITIAL DRAFT (Attempt 0)" if n_attempts == 0 else f"REFINEMENT STEP {n_attempts}"
        print(f"\n--------------------------------------------------------")
        print(f" >>> [{step_label}]")
        print(f"--------------------------------------------------------")
        print(f"Generated Sentence  : \"{sent}\"")
        print(f"Missing Concepts    : {concept_fb}")
        print(f"Commonsense Critique: {commonsense_fb}")

        if concept_fb.lower() == "none" and commonsense_fb.lower() == "none":
            print(f"\n[Success] All constraints satisfied! Stopping early.")
            break

        n_attempts += 1

    return sent_to_fb


def run_cmd():
    concepts = sys.argv[2:]
    max_attempts = 5
    sent_to_fb = autofb_commongen(
        concepts=concepts,
        max_attempts=max_attempts,
    )

    if not sent_to_fb:
        print("\nNo output generated.")
        return

    # Print summary progression
    print("\n" + "=" * 65)
    print("                     REFINEMENT SUMMARY")
    print("=" * 65)
    print(f"{'Step':<8} {'Status':<25} {'Sentence Preview'}")
    print("-" * 65)
    for idx, item in enumerate(sent_to_fb):
        is_clean = (item['concept_feedback'] == ['none'] or item['concept_feedback'] == ['NONE']) and item['commonsense_feedback'].lower() == 'none'
        status = "★ PASSED (ALL SATISFIED)" if is_clean else ("Needs Refinement" if idx > 0 else "Initial Draft")
        preview = item['sentence'][:30] + ("..." if len(item['sentence']) > 30 else "")
        print(f"{idx:<8} {status:<25} \"{preview}\"")
    print("-" * 65)

    # Final accepted sentence
    final_item = sent_to_fb[-1]
    print("\n" + "#" * 65)
    print("                   FINAL ACCEPTED SENTENCE")
    print("#" * 65)
    print(f"Sentence : \"{final_item['sentence']}\"")
    print(f"Concepts : {concepts}")
    print(f"Missing  : {', '.join(final_item['concept_feedback'])}")
    print(f"Critique : {final_item['commonsense_feedback']}")
    print("#" * 65 + "\n")



def run_iter(inputs_file_path: str, max_attempts: int = 4):
    test_df = pd.read_json(inputs_file_path, lines=True, orient="records")
    # add new columns sent_to_fb of type object, and status of type string

    is_rerun = "status" in test_df.columns
    if not is_rerun:
        test_df["sent_to_fb"] = None
        test_df["sent_to_fb"] = test_df["sent_to_fb"].astype(object)
        test_df["status"] = None
    else:
        print("Status column already exists! Looks like you're trying to do a re-run")
        print(test_df["status"].value_counts())
    for i, row in tqdm(test_df.iterrows(), total=len(test_df), desc="Running autofb iter"):
        if row["status"] == "success":
            continue
        try:
            sent_to_fb = autofb_commongen(concepts=row["concepts"], max_attempts=max_attempts)
            test_df.loc[i, "sent_to_fb"] = sent_to_fb
            test_df.loc[i, "status"] = "success"
        except Exception as e:
            test_df.loc[i, "sent_to_fb"] = str(e)
            test_df.loc[i, "status"] = "error"

    output_path = inputs_file_path + (".iter.out" if not is_rerun else ".v0")
    version = 0
    while pathlib.Path(output_path).exists():
        output_path = output_path + f".v{version}"
        version += 1

    test_df.to_json(output_path, orient="records", lines=True)


def run_multi_sample(inputs_file_path: str, n_samples: int = 4):
    test_df = pd.read_json(inputs_file_path, lines=True, orient="records")

    is_rerun = "status" in test_df.columns
    if not is_rerun:
        test_df["outputs"] = None
        test_df["outputs"] = test_df["outputs"].astype(object)
        test_df["status"] = None
    else:
        print("Status column already exists! Looks like you're trying to do a re-run")
        print(test_df["status"].value_counts())

    task_init = CommongenTaskInit(engine=ENGINE, prompt_examples="data/prompt/commongen/init.jsonl")
    task_feedback = CommongenFeedback(
        engine=ENGINE, prompt_examples="data/prompt/commongen/feedback.v1.jsonl"
    )
    for i, row in tqdm(test_df.iterrows(), total=len(test_df), desc="Running multisample autofb"):

        if row["status"] == "success":
            continue
        try:
            outputs = []
            for _ in range(n_samples):
                sent = task_init(concepts=row["concepts"])
                print(sent)
                concept_fb, commonsense_fb = task_feedback(concepts=row["concepts"], sentence=sent)
                print(concept_fb, commonsense_fb)
                outputs.append(
                    {
                        "sentence": sent,
                        "concept_feedback": [f.strip() for f in concept_fb.split(",")],
                        "commonsense_feedback": commonsense_fb,
                    }
                )
                if concept_fb.lower() == "none" and commonsense_fb.lower() == "none":
                    break
            test_df.loc[i, "outputs"] = outputs
            test_df.loc[i, "status"] = "success"
        except Exception as e:
            raise e
            test_df.loc[i, "outputs"] = str(e)
            test_df.loc[i, "status"] = "error"
    print(test_df)
    output_path = inputs_file_path + "." + ENGINE + (".multi.out" if not is_rerun else ".v0")
    version = 0
    while pathlib.Path(output_path).exists():
        output_path = output_path + f".v{version}"
        version += 1

    test_df.to_json(output_path, orient="records", lines=True)


if __name__ == "__main__":
    import sys
    import pandas as pd

    if sys.argv[1] == "cmd":
        run_cmd()

    elif sys.argv[1] == "batch-iter":
        run_iter(inputs_file_path=sys.argv[2])

    elif sys.argv[1] == "batch-multi":
        run_multi_sample(inputs_file_path=sys.argv[2])

    else:
        raise ValueError("Invalid mode: choose between cmd, batch-iter, batch-multi")


