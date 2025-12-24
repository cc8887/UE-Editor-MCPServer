import unreal

def modify_my_actor_blueprint():
    # Define the path to the blueprint
    # Assuming the "Blueprint folder" means /Game/Blueprint
    bp_path = "/Game/Blueprint/MyActor"
    
    # Load the blueprint asset
    bp_asset = unreal.load_asset(bp_path)
    
    if not bp_asset:
        unreal.log_error(f"Failed to load Blueprint: {bp_path}")
        return
        
    if not isinstance(bp_asset, unreal.Blueprint):
        unreal.log_error(f"Asset is not a Blueprint: {bp_path}")
        return

    unreal.log(f"Processing Blueprint: {bp_asset.get_name()}")

    # 1. Clean up existing variables if they exist
    # We access the 'new_variables' property which contains user-created variables
    vars_prop = bp_asset.get_editor_property("new_variables")
    
    targets = ["MyBooleanVar", "MyBooleanArrayVar"]
    vars_to_keep = []
    has_changes = False
    
    for var in vars_prop:
        if var.var_name in targets:
            unreal.log(f"Removing existing variable: {var.var_name}")
            has_changes = True
        else:
            vars_to_keep.append(var)
            
    if has_changes:
        bp_asset.set_editor_property("new_variables", vars_to_keep)
        # Compile to ensure removal is processed before adding new ones
        unreal.BlueprintEditorLibrary.compile_blueprint(bp_asset)

    # 2. Add MyBooleanVar (Boolean)
    # add_member_variable adds a variable with the given type string (e.g., "bool", "int", "float")
    unreal.log("Adding MyBooleanVar...")
    bp_asset.add_member_variable("MyBooleanVar", "bool")
    
    # 3. Add MyBooleanArrayVar (Boolean Array)
    unreal.log("Adding MyBooleanArrayVar...")
    bp_asset.add_member_variable("MyBooleanArrayVar", "bool")
    
    # Retrieve variables again to modify the second one to be an array
    # Note: We must fetch the property again to see the newly added variables
    vars_prop = bp_asset.get_editor_property("new_variables")
    vars_modified = False
    
    updated_vars = []
    for var in vars_prop:
        if var.var_name == "MyBooleanArrayVar":
            # Change container type to Array
            var_type = var.var_type
            if var_type.container_type != unreal.PinContainerType.ARRAY:
                var_type.container_type = unreal.PinContainerType.ARRAY
                var.var_type = var_type
                vars_modified = True
        updated_vars.append(var)
    
    if vars_modified:
        bp_asset.set_editor_property("new_variables", updated_vars)

    # 4. Compile the blueprint
    # This is necessary to regenerate the class so we can access the new properties on the CDO
    unreal.BlueprintEditorLibrary.compile_blueprint(bp_asset)
    
    # 5. Set default values on the Class Default Object (CDO)
    generated_class = bp_asset.generated_class
    if not generated_class:
        unreal.log_error("Failed to get generated class for Blueprint.")
        return

    cdo = unreal.get_default_object(generated_class)
    
    # Set MyBooleanVar default to True
    try:
        cdo.set_editor_property("MyBooleanVar", True)
        unreal.log("Set MyBooleanVar default to True")
    except Exception as e:
        unreal.log_error(f"Failed to set MyBooleanVar: {e}")

    # Set MyBooleanArrayVar default to [True, True, True]
    try:
        cdo.set_editor_property("MyBooleanArrayVar", [True, True, True])
        unreal.log("Set MyBooleanArrayVar default to [True, True, True]")
    except Exception as e:
        unreal.log_error(f"Failed to set MyBooleanArrayVar: {e}")
    
    # 6. Save the asset
    unreal.EditorAssetLibrary.save_loaded_asset(bp_asset)
    unreal.log("Blueprint modification complete.")

if __name__ == "__main__":
    modify_my_actor_blueprint()
