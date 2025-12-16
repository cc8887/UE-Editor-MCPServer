// Fill out your copyright notice in the Description page of Project Settings.

#include "MCPObjectInformDumpLibrary.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "UObject/UnrealType.h"
#include "UObject/PropertyIterator.h"
#include "Runtime/Launch/Resources/Version.h"

FString UMCPObjectInformDumpLibrary::GetIndent(int32 Indent)
{
	Indent = FMath::Max(Indent, 0);
	return FString::ChrN(Indent * 2, TEXT(' '));
}

bool UMCPObjectInformDumpLibrary::IsBlueprintVisible(const FProperty* Property)
{
	if (!Property)
	{
		return false;
	}

	// Check if property has any Blueprint-visible flags
	const EPropertyFlags BlueprintVisibleFlags = 
		CPF_Edit |                    // EditAnywhere, EditDefaultsOnly, EditInstanceOnly, VisibleAnywhere, etc.
		CPF_BlueprintVisible |        // BlueprintReadOnly, BlueprintReadWrite
		CPF_BlueprintAssignable |     // Blueprint assignable delegates
		CPF_BlueprintCallable;        // Blueprint callable delegates

	return Property->HasAnyPropertyFlags(BlueprintVisibleFlags);
}

bool UMCPObjectInformDumpLibrary::IsBlueprintEditable(const FProperty* Property)
{
	if (!Property)
	{
		return false;
	}

	// 首先检查只读标记，这些标记表示属性不可编辑
	const EPropertyFlags ReadOnlyFlags = 
		CPF_EditConst |               // VisibleAnywhere, VisibleDefaultsOnly, VisibleInstanceOnly 等
		CPF_BlueprintReadOnly |       // 蓝图只读
		CPF_DisableEditOnInstance |   // 实例上不可编辑
		CPF_DisableEditOnTemplate;    // 模板上不可编辑

	// 如果有任何只读标记，直接返回false
	if (Property->HasAnyPropertyFlags(ReadOnlyFlags))
	{
		return false;
	}

	// 检查是否有可编辑标记
	// CPF_Edit: EditAnywhere, EditDefaultsOnly, EditInstanceOnly
	// CPF_BlueprintVisible: BlueprintReadWrite (当没有CPF_BlueprintReadOnly时)
	const EPropertyFlags EditableFlags = 
		CPF_Edit |                    
		CPF_BlueprintVisible;

	// 必须至少有一个可编辑标记
	if (!Property->HasAnyPropertyFlags(EditableFlags))
	{
		return false;
	}

	return true;
}

bool UMCPObjectInformDumpLibrary::IsPropertyModified(const FProperty* Property, const void* ValuePtr, const void* DefaultValuePtr)
{
	if (!Property || !ValuePtr || !DefaultValuePtr)
	{
		return true; // If we can't compare, assume it's modified
	}

	// Use the property's built-in comparison
	return !Property->Identical(ValuePtr, DefaultValuePtr);
}

FString UMCPObjectInformDumpLibrary::DumpBlueprintProperties(const FString& PackagePath, bool bBlueprintVisibleOnly, bool bModifiedOnly)
{
	FString Result;
	
	// Try to load the Blueprint asset
	UBlueprint* Blueprint = LoadObject<UBlueprint>(nullptr, *PackagePath);
	if (!Blueprint)
	{
		return FString::Printf(TEXT("Error: Failed to load Blueprint from path: %s"), *PackagePath);
	}

	Result += FString::Printf(TEXT("=== Blueprint Property Dump ===\n"));
	Result += FString::Printf(TEXT("Package Path: %s\n"), *PackagePath);
	Result += FString::Printf(TEXT("Blueprint Name: %s\n"), *Blueprint->GetName());
	
	// Get the generated class from the Blueprint
	UClass* GeneratedClass = Blueprint->GeneratedClass;
	if (!GeneratedClass)
	{
		return Result + TEXT("Error: Blueprint has no generated class\n");
	}

	Result += FString::Printf(TEXT("Generated Class: %s\n"), *GeneratedClass->GetName());
	
	// Check parent class
	UClass* ParentClass = GeneratedClass->GetSuperClass();
	if (ParentClass)
	{
		Result += FString::Printf(TEXT("Parent Class: %s\n"), *ParentClass->GetName());
	}

	// Create default object to read default values
	UObject* DefaultObject = GeneratedClass->GetDefaultObject();
	if (!DefaultObject)
	{
		return Result + TEXT("Error: Failed to get default object\n");
	}

	Result += FString::Printf(TEXT("Filter: BlueprintVisibleOnly=%s, ModifiedOnly=%s\n"),
		bBlueprintVisibleOnly ? TEXT("true") : TEXT("false"),
		bModifiedOnly ? TEXT("true") : TEXT("false"));

	Result += TEXT("\n=== Properties ===\n");
	
	// Get parent class default object for comparison
	const UObject* ParentDefaultObject = nullptr;
	if (bModifiedOnly && ParentClass)
	{
		ParentDefaultObject = ParentClass->GetDefaultObject();
	}

	TSet<const UObject*> VisitedObjects;
	Result += DumpObjectProperties(DefaultObject, 0, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, ParentDefaultObject);

	return Result;
}

FString UMCPObjectInformDumpLibrary::ExportPropertyValueToText(FProperty* Property, const void* ValuePtr, bool bBlueprintVisibleOnly, bool bModifiedOnly, const void* DefaultValuePtr)
{
	if (!Property || !ValuePtr)
	{
		return TEXT("<null>");
	}

	TSet<const UObject*> DummyVisited;
	return DumpPropertyValue(Property, ValuePtr, 0, DummyVisited, bBlueprintVisibleOnly, bModifiedOnly, DefaultValuePtr);
}

FString UMCPObjectInformDumpLibrary::DumpObjectProperties(const UObject* Object, int32 Indent, TSet<const UObject*>& VisitedObjects, bool bBlueprintVisibleOnly, bool bModifiedOnly, const UObject* DefaultObject)
{
	if (!Object)
	{
		return TEXT("null");
	}

	// Avoid infinite recursion
	if (VisitedObjects.Contains(Object))
	{
		return FString::Printf(TEXT("[Circular Reference: %s]"), *Object->GetName());
	}
	VisitedObjects.Add(Object);

	return DumpStructProperties(Object->GetClass(), Object, Indent, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, DefaultObject);
}

FString UMCPObjectInformDumpLibrary::DumpStructProperties(const UStruct* Struct, const void* StructPtr, int32 Indent, TSet<const UObject*>& VisitedObjects, bool bBlueprintVisibleOnly, bool bModifiedOnly, const void* DefaultStructPtr)
{
	FString Result;
	FString IndentStr = GetIndent(Indent);

	// Iterate through all properties
	for (TFieldIterator<FProperty> PropIt(Struct); PropIt; ++PropIt)
	{
		FProperty* Property = *PropIt;
		
		// Check Blueprint visibility filter
		if (bBlueprintVisibleOnly && !IsBlueprintEditable(Property))
		{
			continue;
		}

		// Get property value pointer
		const void* ValuePtr = Property->ContainerPtrToValuePtr<void>(StructPtr);
		
		// Get default value pointer for comparison
		const void* DefaultValuePtr = nullptr;
		if (DefaultStructPtr)
		{
			DefaultValuePtr = Property->ContainerPtrToValuePtr<void>(DefaultStructPtr);
		}

		// Check modified filter
		if (bModifiedOnly && DefaultValuePtr && !IsPropertyModified(Property, ValuePtr, DefaultValuePtr))
		{
			continue;
		}

		// Get property name and type
		FString PropertyName = Property->GetName();
		FString PropertyType = Property->GetCPPType();
		FString PropertyClass = Property->GetClass()->GetName();

		// Get property value as string
		FString ValueStr = DumpPropertyValue(Property, ValuePtr, Indent + 1, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, DefaultValuePtr);

		Result += FString::Printf(TEXT("%sProperty: %s\n"), *IndentStr, *PropertyName);
		Result += FString::Printf(TEXT("%s  Type: %s\n"), *IndentStr, *PropertyType);
		Result += FString::Printf(TEXT("%s  PropertyClass: %s\n"), *IndentStr, *PropertyClass);
		Result += FString::Printf(TEXT("%s  Value: %s\n"), *IndentStr, *ValueStr);
		Result += TEXT("\n");
	}

	return Result;
}

FString UMCPObjectInformDumpLibrary::DumpPropertyValue(FProperty* Property, const void* ValuePtr, int32 Indent, TSet<const UObject*>& VisitedObjects, bool bBlueprintVisibleOnly, bool bModifiedOnly, const void* DefaultValuePtr)
{
	if (!Property || !ValuePtr)
	{
		return TEXT("null");
	}

	FString IndentStr = GetIndent(Indent);
	FString Result;

	// Handle different property types
	if (FBoolProperty* BoolProp = CastField<FBoolProperty>(Property))
	{
		bool Value = BoolProp->GetPropertyValue(ValuePtr);
		return Value ? TEXT("true") : TEXT("false");
	}
	else if (FNumericProperty* NumericProp = CastField<FNumericProperty>(Property))
	{
		if (NumericProp->IsInteger())
		{
			int64 Value = NumericProp->GetSignedIntPropertyValue(ValuePtr);
			return FString::Printf(TEXT("%lld"), Value);
		}
		else if (NumericProp->IsFloatingPoint())
		{
			double Value = NumericProp->GetFloatingPointPropertyValue(ValuePtr);
			return FString::Printf(TEXT("%f"), Value);
		}
	}
	else if (FStrProperty* StrProp = CastField<FStrProperty>(Property))
	{
		const FString* Value = StrProp->GetPropertyValuePtr(ValuePtr);
		return Value ? FString::Printf(TEXT("\"%s\""), **Value) : TEXT("\"\"");
	}
	else if (FNameProperty* NameProp = CastField<FNameProperty>(Property))
	{
		FName Value = NameProp->GetPropertyValue(ValuePtr);
		return FString::Printf(TEXT("\"%s\""), *Value.ToString());
	}
	else if (FTextProperty* TextProp = CastField<FTextProperty>(Property))
	{
		FText Value = TextProp->GetPropertyValue(ValuePtr);
		return FString::Printf(TEXT("\"%s\""), *Value.ToString());
	}
	else if (FEnumProperty* EnumProp = CastField<FEnumProperty>(Property))
	{
		UEnum* EnumDef = EnumProp->GetEnum();
		FNumericProperty* UnderlyingProp = EnumProp->GetUnderlyingProperty();
		int64 EnumValue = UnderlyingProp->GetSignedIntPropertyValue(ValuePtr);
		
		if (EnumDef)
		{
			FString EnumName = EnumDef->GetNameStringByValue(EnumValue);
			return FString::Printf(TEXT("%s (%lld)"), *EnumName, EnumValue);
		}
		return FString::Printf(TEXT("%lld"), EnumValue);
	}
	else if (FByteProperty* ByteProp = CastField<FByteProperty>(Property))
	{
		if (UEnum* EnumDef = ByteProp->Enum)
		{
			uint8 ByteValue = ByteProp->GetPropertyValue(ValuePtr);
			FString EnumName = EnumDef->GetNameStringByValue(ByteValue);
			return FString::Printf(TEXT("%s (%d)"), *EnumName, ByteValue);
		}
		else
		{
			uint8 Value = ByteProp->GetPropertyValue(ValuePtr);
			return FString::Printf(TEXT("%d"), Value);
		}
	}
	else if (FStructProperty* StructProp = CastField<FStructProperty>(Property))
	{
		UScriptStruct* ScriptStruct = StructProp->Struct;
		Result = FString::Printf(TEXT("{\n"));
		Result += DumpStructProperties(ScriptStruct, ValuePtr, Indent, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, DefaultValuePtr);
		Result += FString::Printf(TEXT("%s}"), *GetIndent(Indent - 1));
		return Result;
	}
	else if (FObjectProperty* ObjectProp = CastField<FObjectProperty>(Property))
	{
		UObject* Object = ObjectProp->GetObjectPropertyValue(ValuePtr);
		if (!Object)
		{
			return TEXT("null");
		}
		
		// For simple reference, just show the path
		FString ObjectPath = Object->GetPathName();
		FString ObjectClass = Object->GetClass()->GetName();
		
		// Check if we should recursively dump this object
		// Only dump objects that are subobjects of the main object (not external references)
		if (Object->IsA<UClass>() || Object->IsA<UBlueprint>() || Object->IsA<UPackage>())
		{
			// Don't recursively dump class/blueprint/package references
			return FString::Printf(TEXT("%s [%s]"), *ObjectPath, *ObjectClass);
		}
		
		// Check if this object was already visited
		if (VisitedObjects.Contains(Object))
		{
			return FString::Printf(TEXT("[Circular Reference: %s (%s)]"), *Object->GetName(), *ObjectClass);
		}
		
		// For other objects, show path and optionally dump if it's a subobject
		Result = FString::Printf(TEXT("%s [%s]"), *Object->GetName(), *ObjectClass);
		
		// Only recursively dump if the object is relatively small (has few properties)
		// This prevents dumping large objects
		int32 PropertyCount = 0;
		for (TFieldIterator<FProperty> It(Object->GetClass(), EFieldIteratorFlags::ExcludeSuper); It; ++It)
		{
			PropertyCount++;
			if (PropertyCount > 20)
			{
				break;
			}
		}
		
		if (PropertyCount <= 20 && PropertyCount > 0)
		{
			Result += TEXT(" {\n");
			Result += DumpObjectProperties(Object, Indent, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, nullptr);
			Result += FString::Printf(TEXT("%s}"), *GetIndent(Indent - 1));
		}
		
		return Result;
	}
	else if (FClassProperty* ClassProp = CastField<FClassProperty>(Property))
	{
		UClass* ClassValue = Cast<UClass>(ClassProp->GetObjectPropertyValue(ValuePtr));
		if (ClassValue)
		{
			return FString::Printf(TEXT("Class'%s'"), *ClassValue->GetPathName());
		}
		return TEXT("null");
	}
	else if (FSoftObjectProperty* SoftObjectProp = CastField<FSoftObjectProperty>(Property))
	{
		const FSoftObjectPtr& SoftObject = *reinterpret_cast<const FSoftObjectPtr*>(ValuePtr);
		return FString::Printf(TEXT("SoftObject'%s'"), *SoftObject.ToString());
	}
	else if (FSoftClassProperty* SoftClassProp = CastField<FSoftClassProperty>(Property))
	{
		const FSoftObjectPtr& SoftClass = *reinterpret_cast<const FSoftObjectPtr*>(ValuePtr);
		return FString::Printf(TEXT("SoftClass'%s'"), *SoftClass.ToString());
	}
	else if (FWeakObjectProperty* WeakObjectProp = CastField<FWeakObjectProperty>(Property))
	{
		const FWeakObjectPtr& WeakObject = *reinterpret_cast<const FWeakObjectPtr*>(ValuePtr);
		UObject* Object = WeakObject.Get();
		if (Object)
		{
			return FString::Printf(TEXT("WeakRef'%s' [%s]"), *Object->GetName(), *Object->GetClass()->GetName());
		}
		return TEXT("WeakRef'null'");
	}
	else if (FLazyObjectProperty* LazyObjectProp = CastField<FLazyObjectProperty>(Property))
	{
		const FLazyObjectPtr& LazyObject = *reinterpret_cast<const FLazyObjectPtr*>(ValuePtr);
		UObject* Object = LazyObject.Get();
		if (Object)
		{
			return FString::Printf(TEXT("LazyRef'%s' [%s]"), *Object->GetName(), *Object->GetClass()->GetName());
		}
		return TEXT("LazyRef'null'");
	}
	else if (FInterfaceProperty* InterfaceProp = CastField<FInterfaceProperty>(Property))
	{
		const FScriptInterface& Interface = *reinterpret_cast<const FScriptInterface*>(ValuePtr);
		UObject* Object = Interface.GetObject();
		if (Object)
		{
			return FString::Printf(TEXT("Interface'%s' [%s]"), *Object->GetName(), *Object->GetClass()->GetName());
		}
		return TEXT("Interface'null'");
	}
	else if (FArrayProperty* ArrayProp = CastField<FArrayProperty>(Property))
	{
		FScriptArrayHelper ArrayHelper(ArrayProp, ValuePtr);
		int32 ArrayNum = ArrayHelper.Num();
		
		if (ArrayNum == 0)
		{
			return TEXT("[]");
		}
		
		Result = FString::Printf(TEXT("[Count: %d]\n"), ArrayNum);
		
		// Limit output for large arrays
		int32 MaxElements = FMath::Min(ArrayNum, 10);
		for (int32 i = 0; i < MaxElements; i++)
		{
			void* ElementPtr = ArrayHelper.GetRawPtr(i);
			FString ElementValue = DumpPropertyValue(ArrayProp->Inner, ElementPtr, Indent + 1, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, nullptr);
			Result += FString::Printf(TEXT("%s  [%d]: %s\n"), *IndentStr, i, *ElementValue);
		}
		
		if (ArrayNum > MaxElements)
		{
			Result += FString::Printf(TEXT("%s  ... and %d more elements\n"), *IndentStr, ArrayNum - MaxElements);
		}
		
		return Result;
	}
	else if (FSetProperty* SetProp = CastField<FSetProperty>(Property))
	{
		FScriptSetHelper SetHelper(SetProp, ValuePtr);
		int32 SetNum = SetHelper.Num();
		
		if (SetNum == 0)
		{
			return TEXT("Set{}");
		}
		
		Result = FString::Printf(TEXT("Set{Count: %d}\n"), SetNum);
		
		int32 ElementIndex = 0;
		int32 MaxElements = FMath::Min(SetNum, 10);
		for (int32 i = 0; ElementIndex < MaxElements && i < SetHelper.GetMaxIndex(); i++)
		{
			if (SetHelper.IsValidIndex(i))
			{
				void* ElementPtr = SetHelper.GetElementPtr(i);
				FString ElementValue = DumpPropertyValue(SetProp->ElementProp, ElementPtr, Indent + 1, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, nullptr);
				Result += FString::Printf(TEXT("%s  {%d}: %s\n"), *IndentStr, ElementIndex, *ElementValue);
				ElementIndex++;
			}
		}
		
		if (SetNum > MaxElements)
		{
			Result += FString::Printf(TEXT("%s  ... and %d more elements\n"), *IndentStr, SetNum - MaxElements);
		}
		
		return Result;
	}
	else if (FMapProperty* MapProp = CastField<FMapProperty>(Property))
	{
		FScriptMapHelper MapHelper(MapProp, ValuePtr);
		int32 MapNum = MapHelper.Num();
		
		if (MapNum == 0)
		{
			return TEXT("Map{}");
		}
		
		Result = FString::Printf(TEXT("Map{Count: %d}\n"), MapNum);
		
		int32 ElementIndex = 0;
		int32 MaxElements = FMath::Min(MapNum, 10);
		for (int32 i = 0; ElementIndex < MaxElements && i < MapHelper.GetMaxIndex(); i++)
		{
			if (MapHelper.IsValidIndex(i))
			{
				void* KeyPtr = MapHelper.GetKeyPtr(i);
				void* ValuePtr2 = MapHelper.GetValuePtr(i);
				
				FString KeyStr = DumpPropertyValue(MapProp->KeyProp, KeyPtr, Indent + 1, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, nullptr);
				FString ValueStr = DumpPropertyValue(MapProp->ValueProp, ValuePtr2, Indent + 1, VisitedObjects, bBlueprintVisibleOnly, bModifiedOnly, nullptr);
				
				Result += FString::Printf(TEXT("%s  [%s]: %s\n"), *IndentStr, *KeyStr, *ValueStr);
				ElementIndex++;
			}
		}
		
		if (MapNum > MaxElements)
		{
			Result += FString::Printf(TEXT("%s  ... and %d more elements\n"), *IndentStr, MapNum - MaxElements);
		}
		
		return Result;
	}
	else if (FDelegateProperty* DelegateProp = CastField<FDelegateProperty>(Property))
	{
		const FScriptDelegate& Delegate = *reinterpret_cast<const FScriptDelegate*>(ValuePtr);
		if (Delegate.IsBound())
		{
			const UObject* Object = Delegate.GetUObject();
			FName FuncName = Delegate.GetFunctionName();
			return FString::Printf(TEXT("Delegate{Object: %s, Function: %s}"), 
				Object ? *Object->GetName() : TEXT("null"),
				*FuncName.ToString());
		}
		return TEXT("Delegate{Unbound}");
	}
	else if (FMulticastDelegateProperty* MulticastDelegateProp = CastField<FMulticastDelegateProperty>(Property))
	{
		// For multicast delegates, just indicate it exists
		return TEXT("MulticastDelegate{...}");
	}
	else if (FFieldPathProperty* FieldPathProp = CastField<FFieldPathProperty>(Property))
	{
		const FFieldPath& FieldPath = *reinterpret_cast<const FFieldPath*>(ValuePtr);
		return FString::Printf(TEXT("FieldPath'%s'"), *FieldPath.ToString());
	}
	else
	{
		// Fallback: Use ExportTextItem to get string representation
		FString ExportedValue;
#if ENGINE_MAJOR_VERSION >= 5
		Property->ExportTextItem_Direct(ExportedValue, ValuePtr, ValuePtr, nullptr, PPF_None);
#else
		Property->ExportTextItem(ExportedValue, ValuePtr, ValuePtr, nullptr, PPF_None);
#endif
		return ExportedValue;
	}

	return TEXT("Unknown");
}