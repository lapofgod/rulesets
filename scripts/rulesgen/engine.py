from __future__ import annotations

import shutil

from .models import Bundle, EmitContext, GenerationFailure, GeneratorConfig, GenericRuleSet, Rule
from .source import iter_sources, load_rules
from .targets import GenericToTargetTransformer
from .writers import write_manifest, write_type_readme


def run_generation(config: GeneratorConfig) -> int:
    print(f"[INFO] Start generation from {config.source_root} to {config.output_root}")

    if config.output_root.exists():
        shutil.rmtree(config.output_root)

    bundles = iter_sources(config.source_root)
    transformer = GenericToTargetTransformer(config.targets)

    context = EmitContext(
        output_root=config.output_root,
        generated_at=config.generated_at,
        compile_srs=config.compile_srs,
    )

    entries: list[tuple[Bundle, list[Rule]]] = []
    failures: list[GenerationFailure] = []
    readme_index: dict[str, dict[str, list[str]]] = {target: {} for target in config.targets}

    for bundle in bundles:
        print(f"[INFO] Generating '{bundle.name}' from {bundle.source.name} ...")
        try:
            rules = load_rules(bundle)
            file_map = transformer.emit(
                GenericRuleSet(bundle=bundle, rules=rules),
                context=context,
            )
            entries.append((bundle, rules))
            for target, types in file_map.items():
                for rule_type, filenames in types.items():
                    if rule_type not in readme_index[target]:
                        readme_index[target][rule_type] = []
                    readme_index[target][rule_type].extend(filenames)
        except Exception as exc:
            failures.append(GenerationFailure(name=bundle.name, reason=str(exc)))
            print(f"[ERROR] Failed to generate '{bundle.name}': {exc}")

    for target, types in readme_index.items():
        for rule_type, filenames in types.items():
            write_type_readme(
                config.output_root,
                target,
                rule_type,
                filenames,
                config.github_repo,
                config.publish_branch,
            )

    write_manifest(
        config.source_root,
        config.output_root,
        config.ruleset_baseline,
        config.targets,
        entries,
        failures,
    )

    if failures:
        failed_names = ", ".join(item.name for item in failures)
        raise RuntimeError(f"Generation failed for {len(failures)} bundle(s): {failed_names}")
    return len(entries)
