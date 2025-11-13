- Do not set variables in the docker containers once they are deployed. everything must come from the env files. Restart or rebuild if you need to.
- Do not lose the user data unless if I specifically ask for it

- Docker-compose.prod.yml is how we run our production version of this application
- Make sure all processes are NON blocking. We don't want user actions to affect other users or hang stuff for other users.