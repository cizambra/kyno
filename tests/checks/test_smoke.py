import kyno


def test_given_the_installed_package_when_importing_then_a_version_is_exposed():
    assert kyno.__version__ == "0.1.0"
