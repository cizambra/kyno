from kyno.store.sql import SqlConstitutionStore


def create_memory_store():
    store = SqlConstitutionStore(url="sqlite://")
    store.create_all()
    return store
