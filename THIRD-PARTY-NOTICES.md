# Third-Party Software Notices and Licenses

This document contains the licenses and notices for third-party software used in Tesslate Studio.

Tesslate Studio itself is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for the full license text.

---

## Table of Contents

1. [Traefik](#traefik)
2. [PostgreSQL](#postgresql)
3. [Python Dependencies](#python-dependencies)
4. [JavaScript Dependencies](#javascript-dependencies)

---

## Traefik

- **Version**: v3.1
- **License**: MIT License
- **Copyright**: (c) 2016-2020 Containous SAS; 2020-2025 Traefik Labs
- **Website**: https://traefik.io/
- **Source Code**: https://github.com/traefik/traefik
- **Usage**: Reverse proxy for routing and load balancing in local development environments

### MIT License

```
The MIT License (MIT)

Copyright (c) 2016-2020 Containous SAS; 2020-2025 Traefik Labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

---

## PostgreSQL

- **Version**: 15-alpine
- **License**: PostgreSQL License
- **Copyright**: Portions Copyright (c) 1996-2024, The PostgreSQL Global Development Group
- **Website**: https://www.postgresql.org/
- **Source Code**: https://github.com/postgres/postgres
- **Usage**: Relational database system for application data storage

### PostgreSQL License

PostgreSQL is released under the PostgreSQL License, a liberal Open Source license similar to the BSD or MIT licenses.

```
PostgreSQL Database Management System
(formerly known as Postgres, then as Postgres95)

Portions Copyright (c) 1996-2024, PostgreSQL Global Development Group

Portions Copyright (c) 1994, The Regents of the University of California

Permission to use, copy, modify, and distribute this software and its
documentation for any purpose, without fee, and without a written agreement
is hereby granted, provided that the above copyright notice and this
paragraph and the following two paragraphs appear in all copies.

IN NO EVENT SHALL THE UNIVERSITY OF CALIFORNIA BE LIABLE TO ANY PARTY FOR
DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES, INCLUDING
LOST PROFITS, ARISING OUT OF THE USE OF THIS SOFTWARE AND ITS
DOCUMENTATION, EVEN IF THE UNIVERSITY OF CALIFORNIA HAS BEEN ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

THE UNIVERSITY OF CALIFORNIA SPECIFICALLY DISCLAIMS ANY WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS FOR A PARTICULAR PURPOSE.  THE SOFTWARE PROVIDED HEREUNDER IS
ON AN "AS IS" BASIS, AND THE UNIVERSITY OF CALIFORNIA HAS NO OBLIGATIONS TO
PROVIDE MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR MODIFICATIONS.
```

---

## Python Dependencies

The orchestrator backend uses various Python packages with the following licenses:

### FastAPI (MIT License)
- **Website**: https://fastapi.tiangolo.com/
- **License**: MIT License
- **Usage**: Web framework for building the REST API

### SQLAlchemy (MIT License)
- **Website**: https://www.sqlalchemy.org/
- **License**: MIT License
- **Usage**: SQL toolkit and Object-Relational Mapping (ORM)

### Other Python Dependencies

All Python dependencies and their licenses can be inspected in [orchestrator/pyproject.toml](orchestrator/pyproject.toml). The majority of Python packages used in this project are licensed under MIT, BSD, or Apache 2.0 licenses, which are compatible with the project's Apache 2.0 license.

To generate a complete list of Python dependencies and their licenses, run:
```bash
cd orchestrator
uv pip list --format=json | python -c "import json, sys; [print(f\"{pkg['name']}: {pkg['version']}\") for pkg in json.load(sys.stdin)]"
```

---

## JavaScript Dependencies

The frontend application uses various JavaScript/TypeScript packages with the following licenses:

### React (MIT License)
- **Version**: 19.1.1
- **Website**: https://react.dev/
- **License**: MIT License
- **Usage**: UI framework for building the web application

### Vite (MIT License)
- **Version**: 7.1.2
- **Website**: https://vite.dev/
- **License**: MIT License
- **Usage**: Build tool and development server

### Monaco Editor (MIT License)
- **Package**: @monaco-editor/react
- **Version**: 4.7.0
- **Website**: https://microsoft.github.io/monaco-editor/
- **License**: MIT License
- **Usage**: Code editor component for the IDE interface

### TipTap (MIT License)
- **Version**: 3.7.0
- **Website**: https://tiptap.dev/
- **License**: MIT License
- **Usage**: Rich text editor for documentation and notes

### Other JavaScript Dependencies

All JavaScript dependencies and their licenses can be inspected in [app/package.json](app/package.json). The majority of JavaScript packages used in this project are licensed under MIT, BSD, or Apache 2.0 licenses, which are compatible with the project's Apache 2.0 license.

To generate a complete list of JavaScript dependencies and their licenses, run:
```bash
cd app
npm list --json | jq '.dependencies | keys'
```

---

## Additional Notes

### License Compatibility

All third-party licenses used in this project (MIT, BSD, PostgreSQL License) are permissive open-source licenses that are compatible with the Apache License 2.0 under which Tesslate Studio is released.

### Docker Images

This project uses official Docker images for Traefik and PostgreSQL in development and production deployments. These images are not modified or bundled with the Tesslate Studio source code, but are referenced in docker-compose.yml and Kubernetes manifests.

### Kubernetes Components

In production Kubernetes deployments, additional open-source software may be used:
- **NGINX Ingress Controller** (Apache 2.0 License)
- **cert-manager** (Apache 2.0 License)

Please refer to their respective project pages for detailed license information.

---

## Updating This File

When adding new third-party dependencies to this project, please update this file with:
1. The name and version of the dependency
2. The license type
3. A link to the project's website or source code
4. The full license text for major components (MIT, BSD, etc.)

---

*Last Updated: 2025*
