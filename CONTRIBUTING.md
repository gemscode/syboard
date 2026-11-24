# Contributing to Syboard

Thank you for your interest in Syboard. Contributions are welcome from anyone who signs the contributor
agreement and whose change the maintainer approves.

## Before you start

1. Open an issue that describes the change you have in mind, so it can be discussed before you write code.
2. Fork the repository and work on a branch of your fork.

## Your pull request

1. Keep one change per pull request, with tests for what it changes.
2. On your first pull request, the CLA Assistant asks you to sign the
   [Individual Contributor License Agreement](docs/CLA.md). A pull request merges only once it is signed.
3. The tests and the leak scan run on every pull request and must pass.
4. Every change needs the approving review of the repository's owner (see `.github/CODEOWNERS`);
   nobody pushes to `main` directly.

## What never goes into the repository

Keys, tokens, passwords, `.env` files, personal data, and addresses or paths of a particular machine.
The leak scan stops a pull request that holds any of them.

## License

By contributing, you agree that your contribution is licensed under the Apache License 2.0 (see LICENSE)
and under the terms of the contributor agreement.
