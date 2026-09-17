"""past5loc - Chinese localization toolkit for the PAST statistics application.

Public API:
    pe.PEFile              read/patch/write PE resources
    formstream.parse       parse a TPF0 form stream
    formstream.walk_strings  enumerate translatable string tokens
    formstream.patch_strings rewrite them
    catalog                build a translation worklist from an executable
    builder                produce a localized executable
"""
__version__ = '1.0.0'
