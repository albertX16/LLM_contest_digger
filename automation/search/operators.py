"""Type-safe mutation, crossover and deduplication."""

from __future__ import annotations

from .genome import (
    COMBINE_OPS,
    ExpressionBlock,
    Genome,
    random_block,
    validate_genome,
)


def _clone(genome: Genome) -> Genome:
    return Genome.from_dict(genome.to_dict())


def mutate(genome: Genome, rng, rate: float,
           search_space: dict | None = None, *, sampler=None,
           trace: list[str] | None = None) -> Genome:
    space = search_space or {}
    allowed_ops = space.get("allowed_ops")
    allowed_fields = space.get("allowed_fields")
    combines = tuple(space.get("preferred_combines") or COMBINE_OPS)
    out = _clone(genome)
    for index, block in enumerate(list(out.blocks)):
        if rng.random() >= rate:
            continue
        actions = ["replace", "sign"]
        if "window" in block.params:
            actions.append("window")
        if block.inputs and allowed_fields:
            actions.append("input")
        action = (sampler.choose(rng, "mutation_action", actions)
                  if sampler is not None else str(rng.choice(actions)))
        if trace is not None:
            trace.append(action)
        if action == "replace":
            out.blocks[index] = random_block(
                rng, allowed_ops=allowed_ops, allowed_fields=allowed_fields,
                sampler=sampler)
        elif action == "sign":
            block.sign = "-" if block.sign == "+" else "+"
        elif action == "window" and "window" in block.params:
            windows = (2, 3, 5, 8, 13, 21, 34)
            block.params["window"] = int(
                sampler.choose(rng, "window", windows) if sampler is not None
                else rng.choice(windows))
        elif action == "input" and block.inputs and allowed_fields:
            replacement = (sampler.choose(rng, "field", tuple(allowed_fields))
                           if sampler is not None else str(rng.choice(tuple(allowed_fields))))
            position = int(rng.integers(0, len(block.inputs)))
            if len(block.inputs) == 1 or replacement not in block.inputs:
                block.inputs[position] = replacement
    if rng.random() < rate * 0.5:
        out.combine = (sampler.choose(rng, "combine", combines)
                       if sampler is not None else str(rng.choice(combines)))
        if trace is not None:
            trace.append("combine")
    errors = validate_genome(out)
    if errors:
        raise ValueError("mutation produced invalid genome: " + "; ".join(errors))
    return out


def crossover(left: Genome, right: Genome, rng) -> Genome:
    if not left.blocks or not right.blocks:
        return _clone(left)
    left_cut = int(rng.integers(1, len(left.blocks) + 1))
    right_cut = int(rng.integers(0, len(right.blocks)))
    blocks = [ExpressionBlock.from_dict(x.to_dict())
              for x in left.blocks[:left_cut] + right.blocks[right_cut:]]
    blocks = blocks[:4]
    child = Genome(blocks=blocks or [ExpressionBlock.from_dict(left.blocks[0].to_dict())],
                   combine=left.combine if rng.random() < 0.5 else right.combine)
    errors = validate_genome(child)
    if errors:
        raise ValueError("crossover produced invalid genome: " + "; ".join(errors))
    return child


def dedupe(genomes: list[Genome]) -> list[Genome]:
    seen: set[str] = set()
    unique: list[Genome] = []
    for genome in genomes:
        fingerprint = genome.fingerprint()
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(genome)
    return unique
