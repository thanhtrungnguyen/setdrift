---
name: spring-boot-endpoint
description: >-
  Use when creating or modifying a Spring Boot 4 REST endpoint in this codebase —
  controller + service + DTO + validation + the project's standard error envelope.
  Triggers on requests like "add an endpoint", "expose a REST API for X",
  "new controller", or mentions of @RestController / @GetMapping in the parking services.
  Applies to Spring annotation patterns in the parking services.
---

# Spring Boot Endpoint (parking platform conventions)

> SAMPLE SKILL — this is the optimization *target*. Its `description` above is the
> learned parameter that the Setdrift optimizer (eval/setdrift_eval/optimizer) will tune.

## When this applies
Creating or editing an HTTP endpoint in the CMS API / IAM / Storage services.

## Conventions to enforce
- Controller in `*.web`, service in `*.service`, DTOs in `*.dto` (records, not classes).
- Validate request DTOs with Jakarta Bean Validation; never trust raw input.
- Return the project's standard `ApiResponse<T>` envelope, not bare entities.
- Constructor injection only (no field `@Autowired`).
- Add a slice test (`@WebMvcTest`) and wire it into the existing test profile.

## Anti-patterns to block
- Returning JPA entities directly (lazy-loading / serialization traps).
- `@Transactional` on controllers.
- Business logic in the controller layer.
