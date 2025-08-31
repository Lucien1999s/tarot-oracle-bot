from pprint import pprint
from src.logic import perform_reading

if __name__ == "__main__":
    # Example: draw 3 cards, past/present/future spread
    result = perform_reading(
        num_cards=3,
        spread="three_card",
        seed="demo-seed",
        orientation_prob=0.5,
        question="Should I change my career?",
        explain_with_llm=True  # set True if you want LLM output
    )

    pprint(result, sort_dicts=False)
