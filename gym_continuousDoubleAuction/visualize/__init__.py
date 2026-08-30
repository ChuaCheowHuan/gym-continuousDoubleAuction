"""Plotting and inspection for a finished run.

This file exists so `visualize/` is a package rather than an implicit namespace
portion. Without it `setuptools.find_packages()` did not list it, so a built
wheel carried no `visualize` at all - while doc/01 documents
`python -m gym_continuousDoubleAuction.visualize.run_all` as an entry point. It
worked in-tree and from an editable install, which is why nothing noticed: the
CI packaging job builds a wheel and constructs an env from it, but never
imported this. See doc/15 S3-21.

Deliberately empty otherwise. The modules here are entry points run with
`python -m`, and importing them eagerly would pull matplotlib into any process
that touches the package.

What running them needs
-----------------------
Both optional extras: `[plot]` for matplotlib, and `[rllib]` for torch, which
`visualize_modules` reaches through `train.policy.policy_handler`. So
`pip install gym_continuousDoubleAuction` alone installs these modules but
cannot run them; `pip install "gym_continuousDoubleAuction[plot,rllib]"` can.
"""
