import json

from tqdm import tqdm
from argparse import ArgumentParser

from src.readability.utils import call_gpt
from src.readability.prompts import PROMPT_CRITIQUE, PROMPT_FIX

ROUNDS = 5
FILE_PATH = 'data/tasks/codeclean/code_readability/codenet-python-train.jsonl'

def refine_code(original_code):
    rounds = []
    code = original_code.replace('\n\n', '\n')
    for round_number in range(ROUNDS):
        prompt = PROMPT_CRITIQUE.format(code=code)
        suggestion = call_gpt(prompt, temperature=0.0, stage="feedback")[0]
        prompt = PROMPT_FIX.format(code=code, suggestion=suggestion)
        code = call_gpt(prompt, stage="refinement")[0].strip()
        rounds.append({'suggestion': suggestion, 'updated_code': code})
    return {'original_code': original_code, 'updates': rounds}

def main():
    parser = ArgumentParser()
    parser.add_argument('--file', type=str, default=FILE_PATH)
    parser.add_argument('--output', type=str, default='readability.jsonl')
    args = parser.parse_args()
    
    with open(args.file, 'r') as f:
        examples = [json.loads(line) for line in f.readlines()]
        
    with open(args.output, 'w') as f:    
        for example in tqdm(examples[:5]):
            f.write(json.dumps(refine_code(example['input'])) + '\n')
    
if __name__ == '__main__':
    main()
