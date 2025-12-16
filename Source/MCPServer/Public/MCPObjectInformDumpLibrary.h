// Fill out your copyright notice in the Description page of Project Settings.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MCPObjectInformDumpLibrary.generated.h"

/**
 * Library for dumping UObject reflection information
 */
UCLASS()
class MCPSERVER_API UMCPObjectInformDumpLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Dump all reflected properties of a Blueprint asset by its package path
	 * @param PackagePath The package path of the Blueprint (e.g., "/Game/Blueprints/MyBlueprint")
	 * @param bBlueprintVisibleOnly If true, only dump properties that are visible in Blueprint (EditAnywhere, BlueprintReadWrite, etc.)
	 * @param bModifiedOnly If true, only dump properties whose values differ from the parent class default values
	 * @return A string containing all property names, types, and values in English
	 */
	UFUNCTION(BlueprintCallable, Category = "MCP|ObjectDump")
	static FString DumpBlueprintProperties(const FString& PackagePath, bool bBlueprintVisibleOnly = false, bool bModifiedOnly = false);

	/**
	 * Export a single property value to text using the same formatting as DumpPropertyValue
	 */
	static FString ExportPropertyValueToText(FProperty* Property, const void* ValuePtr, bool bBlueprintVisibleOnly = false, bool bModifiedOnly = false, const void* DefaultValuePtr = nullptr);
	
	/**
	 * Recursively dump a single property value
	 * @param Property The property to dump
	 * @param ValuePtr Pointer to the property value
	 * @param Indent Current indentation level for formatting
	 * @param VisitedObjects Set of already visited objects to prevent infinite recursion
	 * @param bBlueprintVisibleOnly If true, only dump Blueprint visible properties
	 * @param bModifiedOnly If true, only dump modified properties
	 * @param DefaultValuePtr Pointer to the default value for comparison (can be nullptr)
	 * @return Formatted string of the property value
	 */
	static FString DumpPropertyValue(FProperty* Property, const void* ValuePtr, int32 Indent, TSet<const UObject*>& VisitedObjects, bool bBlueprintVisibleOnly, bool bModifiedOnly, const void* DefaultValuePtr);

	/**
	 * Dump all properties of a UObject
	 * @param Object The object to dump
	 * @param Indent Current indentation level
	 * @param VisitedObjects Set of already visited objects
	 * @param bBlueprintVisibleOnly If true, only dump Blueprint visible properties
	 * @param bModifiedOnly If true, only dump modified properties
	 * @param DefaultObject The default object for comparison (can be nullptr)
	 * @return Formatted string of all properties
	 */
	static FString DumpObjectProperties(const UObject* Object, int32 Indent, TSet<const UObject*>& VisitedObjects, bool bBlueprintVisibleOnly, bool bModifiedOnly, const UObject* DefaultObject);

	/**
	 * Dump all properties of a UStruct
	 * @param Struct The struct type
	 * @param StructPtr Pointer to the struct data
	 * @param Indent Current indentation level
	 * @param VisitedObjects Set of already visited objects
	 * @param bBlueprintVisibleOnly If true, only dump Blueprint visible properties
	 * @param bModifiedOnly If true, only dump modified properties
	 * @param DefaultStructPtr Pointer to default struct data for comparison (can be nullptr)
	 * @return Formatted string of all properties
	 */
	static FString DumpStructProperties(const UStruct* Struct, const void* StructPtr, int32 Indent, TSet<const UObject*>& VisitedObjects, bool bBlueprintVisibleOnly, bool bModifiedOnly, const void* DefaultStructPtr);

	/**
	 * Get indentation string
	 * @param Indent Number of indent levels
	 * @return Indentation string
	 */
	static FString GetIndent(int32 Indent);

	/**
	 * Check if a property is visible in Blueprint editor
	 * @param Property The property to check
	 * @return true if the property is visible in Blueprint
	 */
	static bool IsBlueprintVisible(const FProperty* Property);

	/**
	 * Check if a property is editable/writable in Blueprint editor
	 * @param Property The property to check
	 * @return true if the property can be modified in Blueprint
	 */
	static bool IsBlueprintEditable(const FProperty* Property);

	/**
	 * Check if a property value differs from its default value
	 * @param Property The property to check
	 * @param ValuePtr Pointer to the current value
	 * @param DefaultValuePtr Pointer to the default value
	 * @return true if the values are different
	 */
	static bool IsPropertyModified(const FProperty* Property, const void* ValuePtr, const void* DefaultValuePtr);
};
