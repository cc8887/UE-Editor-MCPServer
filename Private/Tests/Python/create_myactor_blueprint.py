import unreal

# Create a new Blueprint asset inheriting from Actor
asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
blueprint_factory = unreal.BlueprintFactory()

# Set the parent class to Actor
blueprint_factory.set_editor_property('ParentClass', unreal.Actor)

# Define the asset path and name
asset_path = '/Game/Blueprints'
asset_name = 'MyActor'
full_asset_path = f"{asset_path}/{asset_name}"

# Check if asset exists and delete it if it does
if unreal.EditorAssetLibrary.does_asset_exist(full_asset_path):
    unreal.EditorAssetLibrary.delete_asset(full_asset_path)
    print(f"Deleted existing asset: {full_asset_path}")

# Create the blueprint asset
blueprint_asset = asset_tools.create_asset(
    asset_name=asset_name,
    package_path=asset_path,
    asset_class=unreal.Blueprint,
    factory=blueprint_factory
)

if blueprint_asset:
    # Save the asset
    unreal.EditorAssetLibrary.save_loaded_asset(blueprint_asset)
    print(f"Successfully created Blueprint: {full_asset_path}")
else:
    print("Failed to create Blueprint")
