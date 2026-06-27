"""Legacy agent package.

The runtime entrypoints use the new state+pipeline architecture. Avoid eager
imports here so standalone helper modules can be imported without pulling in
the old agent graph or LLM dependencies.
"""
