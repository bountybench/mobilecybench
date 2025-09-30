from .constants import ANTHROPIC_DATE_PATTERN, OPENAI_DATE_PATTERN

def strip_date_suffix(model: str) -> str:
    openai_stripped = OPENAI_DATE_PATTERN.sub("", model)
    if openai_stripped != model:
        return openai_stripped
    
    anthropic_stripped = ANTHROPIC_DATE_PATTERN.sub("", model)
    if anthropic_stripped != model:
        return anthropic_stripped
    
    return model