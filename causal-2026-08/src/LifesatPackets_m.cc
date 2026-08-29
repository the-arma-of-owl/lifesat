//
// Generated file, do not edit! Created by opp_msgtool 6.4 from src/LifesatPackets.msg.
//

// Disable warnings about unused variables, empty switch stmts, etc:
#ifdef _MSC_VER
#  pragma warning(disable:4101)
#  pragma warning(disable:4065)
#endif

#if defined(__clang__)
#  pragma clang diagnostic ignored "-Wshadow"
#  pragma clang diagnostic ignored "-Wconversion"
#  pragma clang diagnostic ignored "-Wunused-parameter"
#  pragma clang diagnostic ignored "-Wc++98-compat"
#  pragma clang diagnostic ignored "-Wunreachable-code-break"
#  pragma clang diagnostic ignored "-Wold-style-cast"
#elif defined(__GNUC__)
#  pragma GCC diagnostic ignored "-Wshadow"
#  pragma GCC diagnostic ignored "-Wconversion"
#  pragma GCC diagnostic ignored "-Wunused-parameter"
#  pragma GCC diagnostic ignored "-Wold-style-cast"
#  pragma GCC diagnostic ignored "-Wsuggest-attribute=noreturn"
#  pragma GCC diagnostic ignored "-Wfloat-conversion"
#endif

#include <iostream>
#include <sstream>
#include <memory>
#include <type_traits>
#include "LifesatPackets_m.h"

namespace omnetpp {

// Template pack/unpack rules. They are declared *after* a1l type-specific pack functions for multiple reasons.
// They are in the omnetpp namespace, to allow them to be found by argument-dependent lookup via the cCommBuffer argument

// Packing/unpacking an std::vector
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::vector<T,A>& v)
{
    int n = v.size();
    doParsimPacking(buffer, n);
    for (int i = 0; i < n; i++)
        doParsimPacking(buffer, v[i]);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::vector<T,A>& v)
{
    int n;
    doParsimUnpacking(buffer, n);
    v.resize(n);
    for (int i = 0; i < n; i++)
        doParsimUnpacking(buffer, v[i]);
}

// Packing/unpacking an std::list
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::list<T,A>& l)
{
    doParsimPacking(buffer, (int)l.size());
    for (typename std::list<T,A>::const_iterator it = l.begin(); it != l.end(); ++it)
        doParsimPacking(buffer, (T&)*it);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::list<T,A>& l)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        l.push_back(T());
        doParsimUnpacking(buffer, l.back());
    }
}

// Packing/unpacking an std::set
template<typename T, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::set<T,Tr,A>& s)
{
    doParsimPacking(buffer, (int)s.size());
    for (typename std::set<T,Tr,A>::const_iterator it = s.begin(); it != s.end(); ++it)
        doParsimPacking(buffer, *it);
}

template<typename T, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::set<T,Tr,A>& s)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        T x;
        doParsimUnpacking(buffer, x);
        s.insert(x);
    }
}

// Packing/unpacking an std::map
template<typename K, typename V, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::map<K,V,Tr,A>& m)
{
    doParsimPacking(buffer, (int)m.size());
    for (typename std::map<K,V,Tr,A>::const_iterator it = m.begin(); it != m.end(); ++it) {
        doParsimPacking(buffer, it->first);
        doParsimPacking(buffer, it->second);
    }
}

template<typename K, typename V, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::map<K,V,Tr,A>& m)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        K k; V v;
        doParsimUnpacking(buffer, k);
        doParsimUnpacking(buffer, v);
        m[k] = v;
    }
}

// Default pack/unpack function for arrays
template<typename T>
void doParsimArrayPacking(omnetpp::cCommBuffer *b, const T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimPacking(b, t[i]);
}

template<typename T>
void doParsimArrayUnpacking(omnetpp::cCommBuffer *b, T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimUnpacking(b, t[i]);
}

// Default rule to prevent compiler from choosing base class' doParsimPacking() function
template<typename T>
void doParsimPacking(omnetpp::cCommBuffer *, const T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimPacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

template<typename T>
void doParsimUnpacking(omnetpp::cCommBuffer *, T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimUnpacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

}  // namespace omnetpp


template<typename T>
std::string toStringIfPrintable(const T& t) {
    if constexpr (omnetpp::internal::is_printable<T>::value) {
        std::ostringstream os;
        os << t;
        return os.str();
    }
    return omnetpp::cClassDescriptor::UNPRINTABLE;
}

template<typename T>
bool fromStringIfExtractable(T& t, const char *s) {
    if constexpr (omnetpp::internal::is_extractable<T>::value) {
        std::istringstream is(s);
        is >> t;
        return true;
    }
    return false;
}

namespace lifesat {

Register_Enum(lifesat::SatMode, (lifesat::SatMode::MODE_NOMINAL, lifesat::SatMode::MODE_SAFE, lifesat::SatMode::MODE_PAYLOAD));

Register_Enum(lifesat::CommandType, (lifesat::CommandType::CMD_NOOP, lifesat::CommandType::CMD_SET_PARAM, lifesat::CommandType::CMD_SET_MODE, lifesat::CommandType::CMD_UPDATE));

Register_Class(Telecommand)

Telecommand::Telecommand(const char *name, short kind) : ::omnetpp::cPacket(name, kind)
{
}

Telecommand::Telecommand(const Telecommand& other) : ::omnetpp::cPacket(other)
{
    copy(other);
}

Telecommand::~Telecommand()
{
}

Telecommand& Telecommand::operator=(const Telecommand& other)
{
    if (this == &other) return *this;
    ::omnetpp::cPacket::operator=(other);
    copy(other);
    return *this;
}

void Telecommand::copy(const Telecommand& other)
{
    this->commandId = other.commandId;
    this->sequence = other.sequence;
    this->issuedAt = other.issuedAt;
    this->commandType = other.commandType;
    this->paramKey = other.paramKey;
    this->paramValue = other.paramValue;
    this->targetMode = other.targetMode;
    this->authTag = other.authTag;
    this->payloadDigest = other.payloadDigest;
}

void Telecommand::parsimPack(omnetpp::cCommBuffer *b) const
{
    ::omnetpp::cPacket::parsimPack(b);
    doParsimPacking(b,this->commandId);
    doParsimPacking(b,this->sequence);
    doParsimPacking(b,this->issuedAt);
    doParsimPacking(b,this->commandType);
    doParsimPacking(b,this->paramKey);
    doParsimPacking(b,this->paramValue);
    doParsimPacking(b,this->targetMode);
    doParsimPacking(b,this->authTag);
    doParsimPacking(b,this->payloadDigest);
}

void Telecommand::parsimUnpack(omnetpp::cCommBuffer *b)
{
    ::omnetpp::cPacket::parsimUnpack(b);
    doParsimUnpacking(b,this->commandId);
    doParsimUnpacking(b,this->sequence);
    doParsimUnpacking(b,this->issuedAt);
    doParsimUnpacking(b,this->commandType);
    doParsimUnpacking(b,this->paramKey);
    doParsimUnpacking(b,this->paramValue);
    doParsimUnpacking(b,this->targetMode);
    doParsimUnpacking(b,this->authTag);
    doParsimUnpacking(b,this->payloadDigest);
}

long Telecommand::getCommandId() const
{
    return this->commandId;
}

void Telecommand::setCommandId(long commandId)
{
    this->commandId = commandId;
}

long Telecommand::getSequence() const
{
    return this->sequence;
}

void Telecommand::setSequence(long sequence)
{
    this->sequence = sequence;
}

::omnetpp::simtime_t Telecommand::getIssuedAt() const
{
    return this->issuedAt;
}

void Telecommand::setIssuedAt(::omnetpp::simtime_t issuedAt)
{
    this->issuedAt = issuedAt;
}

int Telecommand::getCommandType() const
{
    return this->commandType;
}

void Telecommand::setCommandType(int commandType)
{
    this->commandType = commandType;
}

const char * Telecommand::getParamKey() const
{
    return this->paramKey.c_str();
}

void Telecommand::setParamKey(const char * paramKey)
{
    this->paramKey = paramKey;
}

double Telecommand::getParamValue() const
{
    return this->paramValue;
}

void Telecommand::setParamValue(double paramValue)
{
    this->paramValue = paramValue;
}

int Telecommand::getTargetMode() const
{
    return this->targetMode;
}

void Telecommand::setTargetMode(int targetMode)
{
    this->targetMode = targetMode;
}

const char * Telecommand::getAuthTag() const
{
    return this->authTag.c_str();
}

void Telecommand::setAuthTag(const char * authTag)
{
    this->authTag = authTag;
}

const char * Telecommand::getPayloadDigest() const
{
    return this->payloadDigest.c_str();
}

void Telecommand::setPayloadDigest(const char * payloadDigest)
{
    this->payloadDigest = payloadDigest;
}

class TelecommandDescriptor : public omnetpp::cClassDescriptor
{
  private:
    mutable const char **propertyNames;
    enum FieldConstants {
        FIELD_commandId,
        FIELD_sequence,
        FIELD_issuedAt,
        FIELD_commandType,
        FIELD_paramKey,
        FIELD_paramValue,
        FIELD_targetMode,
        FIELD_authTag,
        FIELD_payloadDigest,
    };
  public:
    TelecommandDescriptor();
    virtual ~TelecommandDescriptor();

    virtual bool doesSupport(omnetpp::cObject *obj) const override;
    virtual const char **getPropertyNames() const override;
    virtual const char *getProperty(const char *propertyName) const override;
    virtual std::string getValueAsString(omnetpp::any_ptr object) const override;
    virtual void setValueAsString(omnetpp::any_ptr object, const char *value) const override;
    virtual int getFieldCount() const override;
    virtual const char *getFieldName(int field) const override;
    virtual int findField(const char *fieldName) const override;
    virtual unsigned int getFieldTypeFlags(int field) const override;
    virtual const char *getFieldTypeString(int field) const override;
    virtual const char **getFieldPropertyNames(int field) const override;
    virtual const char *getFieldProperty(int field, const char *propertyName) const override;
    virtual int getFieldArraySize(omnetpp::any_ptr object, int field) const override;
    virtual void setFieldArraySize(omnetpp::any_ptr object, int field, int size) const override;

    virtual const char *getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const override;
    virtual std::string getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const override;
    virtual omnetpp::cValue getFieldValue(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const override;

    virtual const char *getFieldStructName(int field) const override;
    virtual omnetpp::any_ptr getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const override;
};

Register_ClassDescriptor(TelecommandDescriptor)

TelecommandDescriptor::TelecommandDescriptor() : omnetpp::cClassDescriptor(omnetpp::opp_typename(typeid(lifesat::Telecommand)), "omnetpp::cPacket")
{
    propertyNames = nullptr;
}

TelecommandDescriptor::~TelecommandDescriptor()
{
    delete[] propertyNames;
}

bool TelecommandDescriptor::doesSupport(omnetpp::cObject *obj) const
{
    return dynamic_cast<Telecommand *>(obj)!=nullptr;
}

const char **TelecommandDescriptor::getPropertyNames() const
{
    if (!propertyNames) {
        static const char *names[] = {  nullptr };
        omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
        const char **baseNames = base ? base->getPropertyNames() : nullptr;
        propertyNames = mergeLists(baseNames, names);
    }
    return propertyNames;
}

const char *TelecommandDescriptor::getProperty(const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? base->getProperty(propertyName) : nullptr;
}

std::string TelecommandDescriptor::getValueAsString(omnetpp::any_ptr object) const
{
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    return ((cObject*)pp)->str();
}

void TelecommandDescriptor::setValueAsString(omnetpp::any_ptr object, const char *value) const
{
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    if (!fromStringIfExtractable(*pp, value))
        cClassDescriptor::setValueAsString(object, value);
}

int TelecommandDescriptor::getFieldCount() const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? 9+base->getFieldCount() : 9;
}

unsigned int TelecommandDescriptor::getFieldTypeFlags(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeFlags(field);
        field -= base->getFieldCount();
    }
    static unsigned int fieldTypeFlags[] = {
        FD_ISEDITABLE,    // FIELD_commandId
        FD_ISEDITABLE,    // FIELD_sequence
        FD_ISEDITABLE,    // FIELD_issuedAt
        FD_ISEDITABLE,    // FIELD_commandType
        FD_ISEDITABLE,    // FIELD_paramKey
        FD_ISEDITABLE,    // FIELD_paramValue
        FD_ISEDITABLE,    // FIELD_targetMode
        FD_ISEDITABLE,    // FIELD_authTag
        FD_ISEDITABLE,    // FIELD_payloadDigest
    };
    return (field >= 0 && field < 9) ? fieldTypeFlags[field] : 0;
}

const char *TelecommandDescriptor::getFieldName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldName(field);
        field -= base->getFieldCount();
    }
    static const char *fieldNames[] = {
        "commandId",
        "sequence",
        "issuedAt",
        "commandType",
        "paramKey",
        "paramValue",
        "targetMode",
        "authTag",
        "payloadDigest",
    };
    return (field >= 0 && field < 9) ? fieldNames[field] : nullptr;
}

int TelecommandDescriptor::findField(const char *fieldName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    int baseIndex = base ? base->getFieldCount() : 0;
    if (strcmp(fieldName, "commandId") == 0) return baseIndex + 0;
    if (strcmp(fieldName, "sequence") == 0) return baseIndex + 1;
    if (strcmp(fieldName, "issuedAt") == 0) return baseIndex + 2;
    if (strcmp(fieldName, "commandType") == 0) return baseIndex + 3;
    if (strcmp(fieldName, "paramKey") == 0) return baseIndex + 4;
    if (strcmp(fieldName, "paramValue") == 0) return baseIndex + 5;
    if (strcmp(fieldName, "targetMode") == 0) return baseIndex + 6;
    if (strcmp(fieldName, "authTag") == 0) return baseIndex + 7;
    if (strcmp(fieldName, "payloadDigest") == 0) return baseIndex + 8;
    return base ? base->findField(fieldName) : -1;
}

const char *TelecommandDescriptor::getFieldTypeString(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeString(field);
        field -= base->getFieldCount();
    }
    static const char *fieldTypeStrings[] = {
        "long",    // FIELD_commandId
        "long",    // FIELD_sequence
        "omnetpp::simtime_t",    // FIELD_issuedAt
        "int",    // FIELD_commandType
        "string",    // FIELD_paramKey
        "double",    // FIELD_paramValue
        "int",    // FIELD_targetMode
        "string",    // FIELD_authTag
        "string",    // FIELD_payloadDigest
    };
    return (field >= 0 && field < 9) ? fieldTypeStrings[field] : nullptr;
}

const char **TelecommandDescriptor::getFieldPropertyNames(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldPropertyNames(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        case FIELD_commandType: {
            static const char *names[] = { "enum", "enum",  nullptr };
            return names;
        }
        case FIELD_targetMode: {
            static const char *names[] = { "enum", "enum",  nullptr };
            return names;
        }
        default: return nullptr;
    }
}

const char *TelecommandDescriptor::getFieldProperty(int field, const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldProperty(field, propertyName);
        field -= base->getFieldCount();
    }
    switch (field) {
        case FIELD_commandType:
            if (!strcmp(propertyName, "enum")) return "CommandType";
            if (!strcmp(propertyName, "enum")) return "lifesat::CommandType";
            return nullptr;
        case FIELD_targetMode:
            if (!strcmp(propertyName, "enum")) return "SatMode";
            if (!strcmp(propertyName, "enum")) return "lifesat::SatMode";
            return nullptr;
        default: return nullptr;
    }
}

int TelecommandDescriptor::getFieldArraySize(omnetpp::any_ptr object, int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldArraySize(object, field);
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        default: return 0;
    }
}

void TelecommandDescriptor::setFieldArraySize(omnetpp::any_ptr object, int field, int size) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldArraySize(object, field, size);
            return;
        }
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set array size of field %d of class 'Telecommand'", field);
    }
}

const char *TelecommandDescriptor::getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldDynamicTypeString(object,field,i);
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        default: return nullptr;
    }
}

std::string TelecommandDescriptor::getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValueAsString(object,field,i);
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        case FIELD_commandId: return long2string(pp->getCommandId());
        case FIELD_sequence: return long2string(pp->getSequence());
        case FIELD_issuedAt: return simtime2string(pp->getIssuedAt());
        case FIELD_commandType: return enum2string(static_cast<int>(pp->getCommandType()), "lifesat::CommandType");
        case FIELD_paramKey: return oppstring2string(pp->getParamKey());
        case FIELD_paramValue: return double2string(pp->getParamValue());
        case FIELD_targetMode: return enum2string(static_cast<int>(pp->getTargetMode()), "lifesat::SatMode");
        case FIELD_authTag: return oppstring2string(pp->getAuthTag());
        case FIELD_payloadDigest: return oppstring2string(pp->getPayloadDigest());
        default: return "";
    }
}

void TelecommandDescriptor::setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValueAsString(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        case FIELD_commandId: pp->setCommandId(string2long(value)); break;
        case FIELD_sequence: pp->setSequence(string2long(value)); break;
        case FIELD_issuedAt: pp->setIssuedAt(string2simtime(value)); break;
        case FIELD_commandType: pp->setCommandType((lifesat::CommandType)string2enum(value, "lifesat::CommandType")); break;
        case FIELD_paramKey: pp->setParamKey((value)); break;
        case FIELD_paramValue: pp->setParamValue(string2double(value)); break;
        case FIELD_targetMode: pp->setTargetMode((lifesat::SatMode)string2enum(value, "lifesat::SatMode")); break;
        case FIELD_authTag: pp->setAuthTag((value)); break;
        case FIELD_payloadDigest: pp->setPayloadDigest((value)); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'Telecommand'", field);
    }
}

omnetpp::cValue TelecommandDescriptor::getFieldValue(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValue(object,field,i);
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        case FIELD_commandId: return (omnetpp::intval_t)(pp->getCommandId());
        case FIELD_sequence: return (omnetpp::intval_t)(pp->getSequence());
        case FIELD_issuedAt: return pp->getIssuedAt().dbl();
        case FIELD_commandType: return pp->getCommandType();
        case FIELD_paramKey: return pp->getParamKey();
        case FIELD_paramValue: return pp->getParamValue();
        case FIELD_targetMode: return pp->getTargetMode();
        case FIELD_authTag: return pp->getAuthTag();
        case FIELD_payloadDigest: return pp->getPayloadDigest();
        default: throw omnetpp::cRuntimeError("Cannot return field %d of class 'Telecommand' as cValue -- field index out of range?", field);
    }
}

void TelecommandDescriptor::setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValue(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        case FIELD_commandId: pp->setCommandId(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_sequence: pp->setSequence(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_issuedAt: pp->setIssuedAt(value.doubleValue()); break;
        case FIELD_commandType: pp->setCommandType((lifesat::CommandType)value.intValue()); break;
        case FIELD_paramKey: pp->setParamKey(value.stringValue()); break;
        case FIELD_paramValue: pp->setParamValue(value.doubleValue()); break;
        case FIELD_targetMode: pp->setTargetMode((lifesat::SatMode)value.intValue()); break;
        case FIELD_authTag: pp->setAuthTag(value.stringValue()); break;
        case FIELD_payloadDigest: pp->setPayloadDigest(value.stringValue()); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'Telecommand'", field);
    }
}

const char *TelecommandDescriptor::getFieldStructName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructName(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    };
}

omnetpp::any_ptr TelecommandDescriptor::getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructValuePointer(object, field, i);
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        default: return omnetpp::any_ptr(nullptr);
    }
}

void TelecommandDescriptor::setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldStructValuePointer(object, field, i, ptr);
            return;
        }
        field -= base->getFieldCount();
    }
    Telecommand *pp = omnetpp::fromAnyPtr<Telecommand>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'Telecommand'", field);
    }
}

Register_Class(Telemetry)

Telemetry::Telemetry(const char *name, short kind) : ::omnetpp::cPacket(name, kind)
{
}

Telemetry::Telemetry(const Telemetry& other) : ::omnetpp::cPacket(other)
{
    copy(other);
}

Telemetry::~Telemetry()
{
}

Telemetry& Telemetry::operator=(const Telemetry& other)
{
    if (this == &other) return *this;
    ::omnetpp::cPacket::operator=(other);
    copy(other);
    return *this;
}

void Telemetry::copy(const Telemetry& other)
{
    this->telemetrySeq = other.telemetrySeq;
    this->sourceTime = other.sourceTime;
    this->batteryVoltage = other.batteryVoltage;
    this->illuminated = other.illuminated;
    this->mode = other.mode;
    this->paramDigest = other.paramDigest;
    this->modeWriteCmdId = other.modeWriteCmdId;
    this->modeWriteSeq = other.modeWriteSeq;
    this->paramWriteProvenance = other.paramWriteProvenance;
    this->rejectedCmdCount = other.rejectedCmdCount;
    this->acceptedCmdCount = other.acceptedCmdCount;
    this->integrityTag = other.integrityTag;
}

void Telemetry::parsimPack(omnetpp::cCommBuffer *b) const
{
    ::omnetpp::cPacket::parsimPack(b);
    doParsimPacking(b,this->telemetrySeq);
    doParsimPacking(b,this->sourceTime);
    doParsimPacking(b,this->batteryVoltage);
    doParsimPacking(b,this->illuminated);
    doParsimPacking(b,this->mode);
    doParsimPacking(b,this->paramDigest);
    doParsimPacking(b,this->modeWriteCmdId);
    doParsimPacking(b,this->modeWriteSeq);
    doParsimPacking(b,this->paramWriteProvenance);
    doParsimPacking(b,this->rejectedCmdCount);
    doParsimPacking(b,this->acceptedCmdCount);
    doParsimPacking(b,this->integrityTag);
}

void Telemetry::parsimUnpack(omnetpp::cCommBuffer *b)
{
    ::omnetpp::cPacket::parsimUnpack(b);
    doParsimUnpacking(b,this->telemetrySeq);
    doParsimUnpacking(b,this->sourceTime);
    doParsimUnpacking(b,this->batteryVoltage);
    doParsimUnpacking(b,this->illuminated);
    doParsimUnpacking(b,this->mode);
    doParsimUnpacking(b,this->paramDigest);
    doParsimUnpacking(b,this->modeWriteCmdId);
    doParsimUnpacking(b,this->modeWriteSeq);
    doParsimUnpacking(b,this->paramWriteProvenance);
    doParsimUnpacking(b,this->rejectedCmdCount);
    doParsimUnpacking(b,this->acceptedCmdCount);
    doParsimUnpacking(b,this->integrityTag);
}

long Telemetry::getTelemetrySeq() const
{
    return this->telemetrySeq;
}

void Telemetry::setTelemetrySeq(long telemetrySeq)
{
    this->telemetrySeq = telemetrySeq;
}

::omnetpp::simtime_t Telemetry::getSourceTime() const
{
    return this->sourceTime;
}

void Telemetry::setSourceTime(::omnetpp::simtime_t sourceTime)
{
    this->sourceTime = sourceTime;
}

double Telemetry::getBatteryVoltage() const
{
    return this->batteryVoltage;
}

void Telemetry::setBatteryVoltage(double batteryVoltage)
{
    this->batteryVoltage = batteryVoltage;
}

bool Telemetry::getIlluminated() const
{
    return this->illuminated;
}

void Telemetry::setIlluminated(bool illuminated)
{
    this->illuminated = illuminated;
}

int Telemetry::getMode() const
{
    return this->mode;
}

void Telemetry::setMode(int mode)
{
    this->mode = mode;
}

const char * Telemetry::getParamDigest() const
{
    return this->paramDigest.c_str();
}

void Telemetry::setParamDigest(const char * paramDigest)
{
    this->paramDigest = paramDigest;
}

long Telemetry::getModeWriteCmdId() const
{
    return this->modeWriteCmdId;
}

void Telemetry::setModeWriteCmdId(long modeWriteCmdId)
{
    this->modeWriteCmdId = modeWriteCmdId;
}

long Telemetry::getModeWriteSeq() const
{
    return this->modeWriteSeq;
}

void Telemetry::setModeWriteSeq(long modeWriteSeq)
{
    this->modeWriteSeq = modeWriteSeq;
}

const char * Telemetry::getParamWriteProvenance() const
{
    return this->paramWriteProvenance.c_str();
}

void Telemetry::setParamWriteProvenance(const char * paramWriteProvenance)
{
    this->paramWriteProvenance = paramWriteProvenance;
}

long Telemetry::getRejectedCmdCount() const
{
    return this->rejectedCmdCount;
}

void Telemetry::setRejectedCmdCount(long rejectedCmdCount)
{
    this->rejectedCmdCount = rejectedCmdCount;
}

long Telemetry::getAcceptedCmdCount() const
{
    return this->acceptedCmdCount;
}

void Telemetry::setAcceptedCmdCount(long acceptedCmdCount)
{
    this->acceptedCmdCount = acceptedCmdCount;
}

const char * Telemetry::getIntegrityTag() const
{
    return this->integrityTag.c_str();
}

void Telemetry::setIntegrityTag(const char * integrityTag)
{
    this->integrityTag = integrityTag;
}

class TelemetryDescriptor : public omnetpp::cClassDescriptor
{
  private:
    mutable const char **propertyNames;
    enum FieldConstants {
        FIELD_telemetrySeq,
        FIELD_sourceTime,
        FIELD_batteryVoltage,
        FIELD_illuminated,
        FIELD_mode,
        FIELD_paramDigest,
        FIELD_modeWriteCmdId,
        FIELD_modeWriteSeq,
        FIELD_paramWriteProvenance,
        FIELD_rejectedCmdCount,
        FIELD_acceptedCmdCount,
        FIELD_integrityTag,
    };
  public:
    TelemetryDescriptor();
    virtual ~TelemetryDescriptor();

    virtual bool doesSupport(omnetpp::cObject *obj) const override;
    virtual const char **getPropertyNames() const override;
    virtual const char *getProperty(const char *propertyName) const override;
    virtual std::string getValueAsString(omnetpp::any_ptr object) const override;
    virtual void setValueAsString(omnetpp::any_ptr object, const char *value) const override;
    virtual int getFieldCount() const override;
    virtual const char *getFieldName(int field) const override;
    virtual int findField(const char *fieldName) const override;
    virtual unsigned int getFieldTypeFlags(int field) const override;
    virtual const char *getFieldTypeString(int field) const override;
    virtual const char **getFieldPropertyNames(int field) const override;
    virtual const char *getFieldProperty(int field, const char *propertyName) const override;
    virtual int getFieldArraySize(omnetpp::any_ptr object, int field) const override;
    virtual void setFieldArraySize(omnetpp::any_ptr object, int field, int size) const override;

    virtual const char *getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const override;
    virtual std::string getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const override;
    virtual omnetpp::cValue getFieldValue(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const override;

    virtual const char *getFieldStructName(int field) const override;
    virtual omnetpp::any_ptr getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const override;
};

Register_ClassDescriptor(TelemetryDescriptor)

TelemetryDescriptor::TelemetryDescriptor() : omnetpp::cClassDescriptor(omnetpp::opp_typename(typeid(lifesat::Telemetry)), "omnetpp::cPacket")
{
    propertyNames = nullptr;
}

TelemetryDescriptor::~TelemetryDescriptor()
{
    delete[] propertyNames;
}

bool TelemetryDescriptor::doesSupport(omnetpp::cObject *obj) const
{
    return dynamic_cast<Telemetry *>(obj)!=nullptr;
}

const char **TelemetryDescriptor::getPropertyNames() const
{
    if (!propertyNames) {
        static const char *names[] = {  nullptr };
        omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
        const char **baseNames = base ? base->getPropertyNames() : nullptr;
        propertyNames = mergeLists(baseNames, names);
    }
    return propertyNames;
}

const char *TelemetryDescriptor::getProperty(const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? base->getProperty(propertyName) : nullptr;
}

std::string TelemetryDescriptor::getValueAsString(omnetpp::any_ptr object) const
{
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    return ((cObject*)pp)->str();
}

void TelemetryDescriptor::setValueAsString(omnetpp::any_ptr object, const char *value) const
{
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    if (!fromStringIfExtractable(*pp, value))
        cClassDescriptor::setValueAsString(object, value);
}

int TelemetryDescriptor::getFieldCount() const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? 12+base->getFieldCount() : 12;
}

unsigned int TelemetryDescriptor::getFieldTypeFlags(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeFlags(field);
        field -= base->getFieldCount();
    }
    static unsigned int fieldTypeFlags[] = {
        FD_ISEDITABLE,    // FIELD_telemetrySeq
        FD_ISEDITABLE,    // FIELD_sourceTime
        FD_ISEDITABLE,    // FIELD_batteryVoltage
        FD_ISEDITABLE,    // FIELD_illuminated
        FD_ISEDITABLE,    // FIELD_mode
        FD_ISEDITABLE,    // FIELD_paramDigest
        FD_ISEDITABLE,    // FIELD_modeWriteCmdId
        FD_ISEDITABLE,    // FIELD_modeWriteSeq
        FD_ISEDITABLE,    // FIELD_paramWriteProvenance
        FD_ISEDITABLE,    // FIELD_rejectedCmdCount
        FD_ISEDITABLE,    // FIELD_acceptedCmdCount
        FD_ISEDITABLE,    // FIELD_integrityTag
    };
    return (field >= 0 && field < 12) ? fieldTypeFlags[field] : 0;
}

const char *TelemetryDescriptor::getFieldName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldName(field);
        field -= base->getFieldCount();
    }
    static const char *fieldNames[] = {
        "telemetrySeq",
        "sourceTime",
        "batteryVoltage",
        "illuminated",
        "mode",
        "paramDigest",
        "modeWriteCmdId",
        "modeWriteSeq",
        "paramWriteProvenance",
        "rejectedCmdCount",
        "acceptedCmdCount",
        "integrityTag",
    };
    return (field >= 0 && field < 12) ? fieldNames[field] : nullptr;
}

int TelemetryDescriptor::findField(const char *fieldName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    int baseIndex = base ? base->getFieldCount() : 0;
    if (strcmp(fieldName, "telemetrySeq") == 0) return baseIndex + 0;
    if (strcmp(fieldName, "sourceTime") == 0) return baseIndex + 1;
    if (strcmp(fieldName, "batteryVoltage") == 0) return baseIndex + 2;
    if (strcmp(fieldName, "illuminated") == 0) return baseIndex + 3;
    if (strcmp(fieldName, "mode") == 0) return baseIndex + 4;
    if (strcmp(fieldName, "paramDigest") == 0) return baseIndex + 5;
    if (strcmp(fieldName, "modeWriteCmdId") == 0) return baseIndex + 6;
    if (strcmp(fieldName, "modeWriteSeq") == 0) return baseIndex + 7;
    if (strcmp(fieldName, "paramWriteProvenance") == 0) return baseIndex + 8;
    if (strcmp(fieldName, "rejectedCmdCount") == 0) return baseIndex + 9;
    if (strcmp(fieldName, "acceptedCmdCount") == 0) return baseIndex + 10;
    if (strcmp(fieldName, "integrityTag") == 0) return baseIndex + 11;
    return base ? base->findField(fieldName) : -1;
}

const char *TelemetryDescriptor::getFieldTypeString(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeString(field);
        field -= base->getFieldCount();
    }
    static const char *fieldTypeStrings[] = {
        "long",    // FIELD_telemetrySeq
        "omnetpp::simtime_t",    // FIELD_sourceTime
        "double",    // FIELD_batteryVoltage
        "bool",    // FIELD_illuminated
        "int",    // FIELD_mode
        "string",    // FIELD_paramDigest
        "long",    // FIELD_modeWriteCmdId
        "long",    // FIELD_modeWriteSeq
        "string",    // FIELD_paramWriteProvenance
        "long",    // FIELD_rejectedCmdCount
        "long",    // FIELD_acceptedCmdCount
        "string",    // FIELD_integrityTag
    };
    return (field >= 0 && field < 12) ? fieldTypeStrings[field] : nullptr;
}

const char **TelemetryDescriptor::getFieldPropertyNames(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldPropertyNames(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        case FIELD_mode: {
            static const char *names[] = { "enum", "enum",  nullptr };
            return names;
        }
        default: return nullptr;
    }
}

const char *TelemetryDescriptor::getFieldProperty(int field, const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldProperty(field, propertyName);
        field -= base->getFieldCount();
    }
    switch (field) {
        case FIELD_mode:
            if (!strcmp(propertyName, "enum")) return "SatMode";
            if (!strcmp(propertyName, "enum")) return "lifesat::SatMode";
            return nullptr;
        default: return nullptr;
    }
}

int TelemetryDescriptor::getFieldArraySize(omnetpp::any_ptr object, int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldArraySize(object, field);
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        default: return 0;
    }
}

void TelemetryDescriptor::setFieldArraySize(omnetpp::any_ptr object, int field, int size) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldArraySize(object, field, size);
            return;
        }
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set array size of field %d of class 'Telemetry'", field);
    }
}

const char *TelemetryDescriptor::getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldDynamicTypeString(object,field,i);
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        default: return nullptr;
    }
}

std::string TelemetryDescriptor::getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValueAsString(object,field,i);
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        case FIELD_telemetrySeq: return long2string(pp->getTelemetrySeq());
        case FIELD_sourceTime: return simtime2string(pp->getSourceTime());
        case FIELD_batteryVoltage: return double2string(pp->getBatteryVoltage());
        case FIELD_illuminated: return bool2string(pp->getIlluminated());
        case FIELD_mode: return enum2string(static_cast<int>(pp->getMode()), "lifesat::SatMode");
        case FIELD_paramDigest: return oppstring2string(pp->getParamDigest());
        case FIELD_modeWriteCmdId: return long2string(pp->getModeWriteCmdId());
        case FIELD_modeWriteSeq: return long2string(pp->getModeWriteSeq());
        case FIELD_paramWriteProvenance: return oppstring2string(pp->getParamWriteProvenance());
        case FIELD_rejectedCmdCount: return long2string(pp->getRejectedCmdCount());
        case FIELD_acceptedCmdCount: return long2string(pp->getAcceptedCmdCount());
        case FIELD_integrityTag: return oppstring2string(pp->getIntegrityTag());
        default: return "";
    }
}

void TelemetryDescriptor::setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValueAsString(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        case FIELD_telemetrySeq: pp->setTelemetrySeq(string2long(value)); break;
        case FIELD_sourceTime: pp->setSourceTime(string2simtime(value)); break;
        case FIELD_batteryVoltage: pp->setBatteryVoltage(string2double(value)); break;
        case FIELD_illuminated: pp->setIlluminated(string2bool(value)); break;
        case FIELD_mode: pp->setMode((lifesat::SatMode)string2enum(value, "lifesat::SatMode")); break;
        case FIELD_paramDigest: pp->setParamDigest((value)); break;
        case FIELD_modeWriteCmdId: pp->setModeWriteCmdId(string2long(value)); break;
        case FIELD_modeWriteSeq: pp->setModeWriteSeq(string2long(value)); break;
        case FIELD_paramWriteProvenance: pp->setParamWriteProvenance((value)); break;
        case FIELD_rejectedCmdCount: pp->setRejectedCmdCount(string2long(value)); break;
        case FIELD_acceptedCmdCount: pp->setAcceptedCmdCount(string2long(value)); break;
        case FIELD_integrityTag: pp->setIntegrityTag((value)); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'Telemetry'", field);
    }
}

omnetpp::cValue TelemetryDescriptor::getFieldValue(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValue(object,field,i);
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        case FIELD_telemetrySeq: return (omnetpp::intval_t)(pp->getTelemetrySeq());
        case FIELD_sourceTime: return pp->getSourceTime().dbl();
        case FIELD_batteryVoltage: return pp->getBatteryVoltage();
        case FIELD_illuminated: return pp->getIlluminated();
        case FIELD_mode: return pp->getMode();
        case FIELD_paramDigest: return pp->getParamDigest();
        case FIELD_modeWriteCmdId: return (omnetpp::intval_t)(pp->getModeWriteCmdId());
        case FIELD_modeWriteSeq: return (omnetpp::intval_t)(pp->getModeWriteSeq());
        case FIELD_paramWriteProvenance: return pp->getParamWriteProvenance();
        case FIELD_rejectedCmdCount: return (omnetpp::intval_t)(pp->getRejectedCmdCount());
        case FIELD_acceptedCmdCount: return (omnetpp::intval_t)(pp->getAcceptedCmdCount());
        case FIELD_integrityTag: return pp->getIntegrityTag();
        default: throw omnetpp::cRuntimeError("Cannot return field %d of class 'Telemetry' as cValue -- field index out of range?", field);
    }
}

void TelemetryDescriptor::setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValue(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        case FIELD_telemetrySeq: pp->setTelemetrySeq(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_sourceTime: pp->setSourceTime(value.doubleValue()); break;
        case FIELD_batteryVoltage: pp->setBatteryVoltage(value.doubleValue()); break;
        case FIELD_illuminated: pp->setIlluminated(value.boolValue()); break;
        case FIELD_mode: pp->setMode((lifesat::SatMode)value.intValue()); break;
        case FIELD_paramDigest: pp->setParamDigest(value.stringValue()); break;
        case FIELD_modeWriteCmdId: pp->setModeWriteCmdId(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_modeWriteSeq: pp->setModeWriteSeq(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_paramWriteProvenance: pp->setParamWriteProvenance(value.stringValue()); break;
        case FIELD_rejectedCmdCount: pp->setRejectedCmdCount(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_acceptedCmdCount: pp->setAcceptedCmdCount(omnetpp::checked_int_cast<long>(value.intValue())); break;
        case FIELD_integrityTag: pp->setIntegrityTag(value.stringValue()); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'Telemetry'", field);
    }
}

const char *TelemetryDescriptor::getFieldStructName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructName(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    };
}

omnetpp::any_ptr TelemetryDescriptor::getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructValuePointer(object, field, i);
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        default: return omnetpp::any_ptr(nullptr);
    }
}

void TelemetryDescriptor::setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldStructValuePointer(object, field, i, ptr);
            return;
        }
        field -= base->getFieldCount();
    }
    Telemetry *pp = omnetpp::fromAnyPtr<Telemetry>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'Telemetry'", field);
    }
}

}  // namespace lifesat

namespace omnetpp {

}  // namespace omnetpp

