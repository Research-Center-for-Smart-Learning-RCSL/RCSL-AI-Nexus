"""A delayed capacity write cannot undo a newer admin edit or heartbeat."""

from dataclasses import replace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import PostgresModelRepository, PostgresNodeRepository
from app.domain.entities.model import ModelState, ResourceProfile
from tests.unit.manage_models_fixtures import NODE, make_model


async def test_capacity_update_changes_only_a_matching_snapshot(database_url):
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    original = make_model()
    try:
        async with sessions() as session:
            await PostgresNodeRepository(session).save(NODE)
            await PostgresModelRepository(session).save(original)
            await session.commit()
        async with sessions() as loader:
            repo = PostgresModelRepository(loader)
            snapshot = await repo.get(original.id)
            async with sessions() as concurrent:
                other = PostgresModelRepository(concurrent)
                await other.save(
                    replace(original, alias="edited", capabilities=frozenset({"assist"}))
                )
                at = (await concurrent.execute(text("SELECT clock_timestamp()"))).scalar_one()
                await other.set_observed(original.id, ModelState.LOADED, 9.5, observed_at=at)
                await concurrent.commit()
            await repo.set_capacity_validated(snapshot, True)
            await loader.commit()
        async with sessions() as session:
            stored = await PostgresModelRepository(session).get(original.id)
            assert stored.alias == "edited" and stored.capabilities == frozenset({"assist"})
            assert stored.observed_state is ModelState.LOADED and stored.observed_memory_gb == 9.5
            assert stored.capacity_validated
            await PostgresModelRepository(session).save(
                replace(
                    stored, capacity_validated=False, resource_profile=ResourceProfile(20, 16384)
                )
            )
            await session.commit()
        async with sessions() as session:
            await PostgresModelRepository(session).set_capacity_validated(snapshot, True)
            await session.commit()
        async with sessions() as session:
            assert not (await PostgresModelRepository(session).get(original.id)).capacity_validated
    finally:
        await engine.dispose()
