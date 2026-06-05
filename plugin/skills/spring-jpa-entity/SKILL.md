---
name: spring-jpa-entity
description: >-
  Use when creating or mapping a JPA/Hibernate persistence-layer entity in this
  codebase — @Entity + @Table + @Column field mapping + @ManyToOne / @OneToMany /
  @JoinColumn associations. Triggers on requests like "add a JPA entity", "map this
  table", "create a Hibernate model", or mentions of @Entity / @Column in the
  parking persistence layer. Applies to Spring annotation patterns in the parking
  services.
---

# Spring JPA Entity (parking platform conventions)

> Confusable-pair partner for spring-boot-endpoint (D-44/D-45). Deliberate partial
> overlap in description ("Spring annotation patterns in the parking services") so
> GEPA can demonstrably reduce cross-firing between web-layer (@RestController)
> and persistence-layer (@Entity) triggers. The `description` above is the learned
> parameter that the SICA optimizer (eval/sica_eval/optimizer) will tune.

## When this applies
Creating or mapping a persistence-layer entity in the IAM / Parking / Storage services.

## Conventions to enforce
- Annotate with `@Entity` + `@Table(name="...")` (explicit table name, never defaulted).
- Map each column with `@Column(name="...", nullable=false)` for non-nullable fields.
- Use `@ManyToOne(fetch=FetchType.LAZY)` + `@JoinColumn` for FK associations.
- Use `@OneToMany(mappedBy="...", cascade=CascadeType.ALL, orphanRemoval=true)` for collections.
- IDs: `@GeneratedValue(strategy=GenerationType.IDENTITY)`.
- No business logic in entity classes; use domain services.

## Anti-patterns to block
- `fetch=FetchType.EAGER` on associations (N+1 trap).
- Mutable public fields (use private + getters/setters or Lombok `@Data`).
- Bidirectional associations without proper `mappedBy` — causes duplicate FK columns.
